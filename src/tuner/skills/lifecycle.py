"""Skill change lifecycle: propose -> apply -> rollback.

Safety invariants:
* Only skills carrying Tuner's managed marker are ever overwritten.
* Writes are atomic, preceded by a backup, and refused on conflict (the
  file changed since the proposal was based on it).
* Nothing is ever `git add`-ed or committed.
* Destinations are confined to the placement's skills directory.
"""

from __future__ import annotations

import difflib
import json
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tuner import __version__, paths
from tuner.config import Config
from tuner.fsutil import atomic_write_text, sha256_text
from tuner.skills import discover, frontmatter, placement
from tuner.skills.validate import validate_skill

AUTO_MAX_CHANGED_LINES = 40


class SkillError(Exception):
    """A skill operation was refused (message is user-facing)."""


@dataclass
class Proposal:
    """Result of `propose`."""

    id: str
    status: str
    action: str
    name: str
    path: Path
    warnings: list[str]
    diff: str


def skills_dir() -> Path:
    """Private working area for proposals, backups, and the change log."""
    return paths.ensure_private_dir(paths.data_dir() / "skills")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _log(entry: dict) -> None:
    """Append to the human-readable change log."""
    line = json.dumps({"at": _now(), **entry}, sort_keys=True)
    with open(skills_dir() / "changes.jsonl", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def unified_diff(old: str, new: str, label: str) -> str:
    """Unified diff text between two versions."""
    return "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True),
        f"a/{label}", f"b/{label}"))


def _changed_lines(diff: str) -> int:
    return sum(1 for ln in diff.splitlines()
               if ln[:1] in "+-" and ln[:3] not in ("+++", "---"))


def _row(conn: sqlite3.Connection, change_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM skill_changes WHERE id=?",
                       (change_id,)).fetchone()
    if row is None:
        raise SkillError(f"unknown skill change: {change_id}")
    return row


def _set(conn: sqlite3.Connection, change_id: str, **cols) -> None:
    sets = ", ".join(f"{k}=?" for k in cols)
    conn.execute(f"UPDATE skill_changes SET {sets} WHERE id=?",
                 (*cols.values(), change_id))
    conn.commit()


def proposal_file(change_id: str) -> Path:
    """Stored proposed content for a change."""
    return skills_dir() / "proposals" / change_id / "SKILL.md"


def existing(conn: sqlite3.Connection, analysis_key: str, rec_id: str
             ) -> sqlite3.Row | None:
    """Change already created for this analysis recommendation."""
    return conn.execute(
        "SELECT * FROM skill_changes WHERE "
        "json_extract(finding_json, '$.finding.analysis_key') = ? AND "
        "json_extract(finding_json, '$.finding.recommendation') = ? "
        "ORDER BY created_at DESC LIMIT 1", (analysis_key, rec_id)
    ).fetchone()


def propose(conn: sqlite3.Connection, cfg: Config, spec: dict,
            finding: dict) -> Proposal:
    """Record a proposed create/update; auto-apply in `auto` mode if safe.

    `spec`: {name, content, scope?}. `finding`: {recommendation_id,
    task_ids, repos, evidence...} stored for audit.
    """
    name, content = str(spec.get("name", "")), str(spec.get("content", ""))
    repo_roots = discover.known_repo_roots(conn)
    place = placement.decide(spec.get("scope") or cfg.skills.scope,
                             finding.get("repos", []), repo_roots,
                             cfg.skills.skill_dir)
    target_dir = place.skill_dir(name)
    target = target_dir / "SKILL.md"
    if not placement.inside(place.base_dir, target_dir) or "/" in name \
            or "\\" in name or name.startswith("."):
        raise SkillError(f"unsafe skill name/path: {name!r}")
    existing = discover.discover(list(repo_roots.values()))
    change_id = "sc_" + uuid.uuid4().hex[:10]
    old, base_hash, status, action = "", None, "proposed", "create"
    if target.exists():
        action = "update"
        old = target.read_text(encoding="utf-8")
        base_hash = sha256_text(old)
        info = next((s for s in existing if s.file == target), None)
        if not (info and info.managed):
            status = "manual"  # never touch unmanaged skills
    elif any(s.name == name and s.scope != "builtin" for s in existing):
        status = "manual"  # same name exists elsewhere; avoid shadowing
    content = frontmatter.set_managed(content, change_id, __version__)
    val = validate_skill(name, content, existing)
    if not val.ok:
        raise SkillError("invalid skill: " + "; ".join(val.errors))
    diff = unified_diff(old, content, f"{name}/SKILL.md")
    if cfg.skills.mode == "suggest" and status == "proposed":
        status = "suggested"
    pf = proposal_file(change_id)
    pf.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(pf, content)
    meta = {"finding": finding, "warnings": val.warnings,
            "placement": place.reason}
    conn.execute(
        "INSERT INTO skill_changes(id, created_at, action, skill_name, "
        "scope, path, status, mode, base_hash, new_hash, finding_json, "
        "repo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (change_id, _now(), action, name, place.scope, str(target), status,
         cfg.skills.mode, base_hash, sha256_text(content),
         json.dumps(meta, sort_keys=True), place.repo))
    conn.commit()
    _log({"event": "proposed", "id": change_id, "status": status,
          "path": str(target)})
    auto_ok = (cfg.skills.mode == "auto" and status == "proposed"
               and not val.warnings
               and _changed_lines(diff) <= AUTO_MAX_CHANGED_LINES)
    if auto_ok:
        apply(conn, change_id)
        status = "applied"
    return Proposal(change_id, status, action, name, target, val.warnings,
                    diff)


def apply(conn: sqlite3.Connection, change_id: str) -> Path:
    """Apply an approved proposal atomically, with backup + conflict check."""
    row = _row(conn, change_id)
    if row["status"] not in ("proposed", "approved"):
        raise SkillError(f"cannot apply a change in status "
                         f"'{row['status']}'")
    target = Path(row["path"])
    content = proposal_file(change_id).read_text(encoding="utf-8")
    if sha256_text(content) != row["new_hash"]:
        raise SkillError("stored proposal was modified; refusing to apply")
    current = target.read_text(encoding="utf-8") if target.exists() else None
    cur_hash = sha256_text(current) if current is not None else None
    if cur_hash != row["base_hash"]:
        _set(conn, change_id, status="conflict")
        raise SkillError("conflict: the skill changed since this proposal "
                         "was made; regenerate the proposal")
    backup = None
    if current is not None:
        backup = skills_dir() / "backups" / change_id / "SKILL.md"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, content)
    _set(conn, change_id, status="applied", applied_at=_now(),
         backup_path=str(backup) if backup else None)
    _log({"event": "applied", "id": change_id, "path": str(target)})
    return target


def reject(conn: sqlite3.Connection, change_id: str) -> None:
    """Dismiss a proposal."""
    _row(conn, change_id)
    _set(conn, change_id, status="rejected")
    _log({"event": "rejected", "id": change_id})


def rollback(conn: sqlite3.Connection, change_id: str,
             force: bool = False) -> None:
    """Undo an applied change (restore backup, or remove a created skill)."""
    row = _row(conn, change_id)
    if row["status"] != "applied":
        raise SkillError("only applied changes can be rolled back")
    target = Path(row["path"])
    cur = sha256_text(target.read_text(encoding="utf-8")) \
        if target.exists() else None
    if cur != row["new_hash"] and not force:
        raise SkillError("the skill was edited after Tuner applied it; "
                         "use --force to overwrite those edits")
    if row["backup_path"]:
        shutil.copy2(row["backup_path"], target)
    elif target.exists():
        target.unlink()
        try:
            target.parent.rmdir()  # only if empty
        except OSError:
            pass
    _set(conn, change_id, status="rolled_back", rolled_back_at=_now())
    _log({"event": "rolled_back", "id": change_id, "path": str(target)})


def show_diff(conn: sqlite3.Connection, change_id: str) -> str:
    """Diff between the stored base version and the proposal."""
    row = _row(conn, change_id)
    target = Path(row["path"])
    new = proposal_file(change_id).read_text(encoding="utf-8")
    old = ""
    if row["backup_path"] and Path(row["backup_path"]).exists():
        old = Path(row["backup_path"]).read_text(encoding="utf-8")
    elif row["base_hash"] and target.exists() and \
            sha256_text(target.read_text(encoding="utf-8")) == \
            row["base_hash"]:
        old = target.read_text(encoding="utf-8")
    return unified_diff(old, new, f"{row['skill_name']}/SKILL.md")
