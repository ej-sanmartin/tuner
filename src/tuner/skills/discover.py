"""Discover Agent Skills visible to Cursor and Claude Code.

Both apps read `.claude/skills/` (project) and `~/.claude/skills/`
(global); Cursor additionally reads `.cursor/skills/` and `.agents/skills/`.
We scan all of them (to avoid duplicates and see what already exists) but
only ever write to the configured canonical dir (default `.claude/skills`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tuner import paths
from tuner.fsutil import sha256_file
from tuner.skills import frontmatter

LABELS = (".claude/skills", ".cursor/skills", ".agents/skills",
          ".codex/skills")
BUILTIN_DIRS = ("skills-cursor",)  # Cursor-managed built-ins


@dataclass
class SkillInfo:
    """One discovered SKILL.md."""

    name: str
    directory: Path
    file: Path
    scope: str  # global | project | builtin
    label: str
    repo_root: str | None
    description: str = ""
    managed: bool = False
    content_hash: str | None = None
    problems: list[str] = field(default_factory=list)


def _read(file: Path, scope: str, label: str, repo: str | None
          ) -> SkillInfo:
    """Parse one SKILL.md leniently, recording problems."""
    info = SkillInfo(file.parent.name, file.parent, file, scope, label, repo,
                     content_hash=sha256_file(file))
    try:
        parsed = frontmatter.parse(file.read_text(encoding="utf-8"))
    except OSError as exc:
        info.problems.append(f"unreadable: {exc}")
        return info
    if parsed is None:
        info.problems.append("missing frontmatter")
        return info
    data, _ = parsed
    info.description = str(data.get("description", ""))
    meta = data.get("metadata")
    info.managed = isinstance(meta, dict) and \
        meta.get("tuner-managed") == "true"
    if data.get("name") and data["name"] != file.parent.name:
        info.problems.append("name does not match folder")
    return info


def _scan(base: Path, scope: str, label: str, repo: str | None
          ) -> list[SkillInfo]:
    """All SKILL.md files below `base` (recursive, nested allowed)."""
    out: list[SkillInfo] = []
    try:
        files = sorted(base.rglob("SKILL.md"))
    except OSError:
        return out
    for f in files:
        if "node_modules" in f.parts:
            continue
        out.append(_read(f, scope, label, repo))
    return out


def discover(repo_roots: list[str] | None = None) -> list[SkillInfo]:
    """Skills in global dirs and in each known repository root."""
    home = paths.user_home()
    found: list[SkillInfo] = []
    for label in LABELS:
        found += _scan(home / label, "global", label, None)
    for builtin in BUILTIN_DIRS:
        found += _scan(home / ".cursor" / builtin, "builtin",
                       f".cursor/{builtin}", None)
    for root in repo_roots or []:
        for label in LABELS:
            found += _scan(Path(root) / label, "project", label, root)
    seen, unique = set(), []
    for s in found:  # symlinks / overlapping scans
        key = str(s.file.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def known_repo_roots(conn) -> dict[str, str]:
    """Map repo name -> project path for repositories seen in sessions."""
    rows = conn.execute(
        "SELECT repo, project_path FROM sessions WHERE repo IS NOT NULL "
        "AND project_path IS NOT NULL GROUP BY repo, project_path")
    return {r["repo"]: r["project_path"] for r in rows}
