"""OpenCode collector: measured tokens in opencode.db.

Session rollups in `session_v2` repeat the per-message totals, so usage
comes from `session_message`. A large gap is recorded, not added twice.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from tuner import paths
from tuner.collectors import local_db as db
from tuner.collectors.base import SourceFile
from tuner.collectors.common import iso_utc, repo_for, tool_target
from tuner.models import ParsedSource, SessionRec, ToolCallRec, TurnRec
from tuner.security.redact import compile_extra, preview

AGENT = "opencode"


def candidate_dbs(extra: list[str] | None = None) -> list[Path]:
    """OpenCode database files that exist."""
    home = paths.user_home()
    cands: list[Path] = []
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        cands.append(Path(xdg) / "opencode" / "opencode.db")
    cands.append(home / ".local" / "share" / "opencode" / "opencode.db")
    if sys.platform == "darwin":
        cands.append(home / "Library" / "Application Support" / "opencode"
                     / "opencode.db")
    cands += [Path(p) for p in extra or []]
    return db.existing(cands)


def _message_tokens(data: dict) -> dict | None:
    """Token object on an assistant message, or None."""
    raw = data.get("tokens")
    if not isinstance(raw, dict):
        return None
    cache = raw.get("cache") if isinstance(raw.get("cache"), dict) else {}
    return {"input": raw.get("input"), "output": raw.get("output"),
            "reasoning": raw.get("reasoning"),
            "cache_read": cache.get("read"), "cache_write": cache.get("write")}


def _model_id(data: dict) -> str | None:
    """Model id from an assistant message."""
    model = data.get("model")
    if isinstance(model, dict):
        return str(model.get("id") or "") or None
    if isinstance(model, str) and model:
        parsed = db.parse_json(model)
        if isinstance(parsed, dict):
            return str(parsed.get("id") or "") or None
        return model
    return None


def _ts(column: object, data: dict) -> str | None:
    """Prefer the column timestamp, then `data.time`."""
    ts = iso_utc(column)
    if ts:
        return ts
    stamp = data.get("time")
    if isinstance(stamp, dict):
        return iso_utc(stamp.get("created") or stamp.get("completed"))
    return iso_utc(stamp)


class OpenCodeCollector:
    """Reads `opencode.db` (one file, replaced wholesale when it changes)."""

    name = AGENT
    optional = True

    def __init__(self, extra_dbs: list[str] | None = None,
                 redact_patterns: list[str] | None = None) -> None:
        self.extra_dbs = extra_dbs or []
        self.extra = compile_extra(redact_patterns or [])

    def discover(self) -> bool:
        """True when an OpenCode database exists."""
        return bool(candidate_dbs(self.extra_dbs))

    def locations(self) -> list[Path]:
        """Database files that will be read."""
        return candidate_dbs(self.extra_dbs)

    def iter_sources(self, since: datetime | None = None
                     ) -> Iterator[SourceFile]:
        """Yield each database that changed since `since`."""
        for path in candidate_dbs(self.extra_dbs):
            src = db.db_source(path, self.name, since)
            if src is not None:
                yield src

    def parse(self, src: SourceFile) -> ParsedSource:
        """Parse one database. Malformed files produce errors, not raises."""
        out = ParsedSource()
        try:
            conn = db.connect_ro(src.path)
        except sqlite3.Error as exc:
            out.errors.append(f"unreadable: {exc}")
            return out
        try:
            _parse(conn, src.path, out, self.extra)
        except sqlite3.Error as exc:
            out.errors.append(f"sqlite: {exc}")
        finally:
            conn.close()
        return out

    def capabilities(self) -> dict:
        """Field-level measurement status."""
        return {
            "agent": self.name,
            "tokens": {"input": "measured", "output": "measured",
                       "cache_write": "measured", "cache_read": "measured"},
            "model": "measured", "timestamps": "measured",
            "tool_calls": "measured", "tool_failures": "unavailable",
            "subagents": "unavailable", "compaction": "unavailable",
            "outcome": "inferred",
            "notes": ["per assistant message in session_message; "
                      "session_v2 rollups are not added again",
                      "reasoning tokens are included in output"],
        }


def _parse(conn: sqlite3.Connection, path: Path, out: ParsedSource,
           extra: list) -> None:
    """Fill `out` from one OpenCode database."""
    if not db.has_table(conn, "session_v2"):
        out.errors.append("opencode.db has no session_v2 table")
        return
    sessions = db.rows(conn, out.errors, (
        "SELECT id, directory, title, parent_id, time_created, "
        "time_updated, tokens_input, tokens_output, tokens_reasoning, "
        "tokens_cache_read, tokens_cache_write FROM session_v2"))
    grouped: dict[str, list] = defaultdict(list)
    if db.has_table(conn, "session_message"):
        for row in db.rows(conn, out.errors, (
                "SELECT id, session_id, type, seq, time_created, data "
                "FROM session_message ORDER BY seq, time_created")):
            grouped[row["session_id"]].append(row)
    for row in sessions:
        _session(row, grouped.get(row["id"], []), path, out, extra)


def _session(row, messages: list, path: Path, out: ParsedSource,
             extra: list) -> None:
    """One OpenCode session: user turns and per-message usage."""
    native = str(row["id"])
    sid = f"{AGENT}:{native}"
    project, repo = repo_for(row["directory"])
    meta = {}
    if row["parent_id"]:
        meta["parent_native_id"] = str(row["parent_id"])
    out.sessions.append(SessionRec(
        sid, AGENT, native, project_path=project, repo=repo,
        title=preview(str(row["title"] or ""), 200, extra) or None,
        started_at=iso_utc(row["time_created"]),
        ended_at=iso_utc(row["time_updated"]), source_path=str(path),
        meta=meta))
    turn_id = None
    seq = 0
    sums = {"input": 0, "output": 0, "reasoning": 0,
            "cache_read": 0, "cache_write": 0}
    for index, msg in enumerate(messages):
        data = db.parse_json(msg["data"])
        if not isinstance(data, dict):
            out.errors.append(f"message {msg['id']} is not an object")
            continue
        kind = msg["type"]
        ts = _ts(msg["time_created"], data)
        if kind == "user":
            text = str(data.get("text") or "")
            turn_id = f"{AGENT}:turn:{msg['id']}"
            out.turns.append(TurnRec(
                turn_id, sid, seq, started_at=ts, ended_at=ts,
                prompt_preview=preview(text, 200, extra),
                prompt_chars=len(text), outcome="completed",
                source_path=str(path), source_line=db.as_int(msg["seq"])))
            seq += 1
        elif kind == "assistant":
            _assistant(msg, data, sid, turn_id, ts, path, index, out, extra,
                       sums)
    _check_rollup(row, native, sums, out)


def _assistant(msg, data, sid, turn_id, ts, path, index, out, extra,
               sums) -> None:
    """Usage and tool calls for one assistant message."""
    tokens = _message_tokens(data)
    if tokens:
        for key in sums:
            sums[key] += db.as_int(tokens.get(key))
        out.usage.append(db.usage_rec(
            AGENT, str(msg["id"]), sid, turn_id, ts, _model_id(data),
            tokens, "opencode_message", None, path, index))
    content = data.get("content")
    if not isinstance(content, list):
        return
    for part_i, part in enumerate(content):
        if not isinstance(part, dict) or part.get("type") != "tool":
            continue
        state = part.get("state") if isinstance(part.get("state"), dict) \
            else {}
        call = str(part.get("callID") or part.get("id") or
                   f"{msg['id']}:{part_i}")
        name = str(part.get("tool") or part.get("name") or "tool")
        inp = state.get("input") if isinstance(state.get("input"), dict) \
            else {}
        out.tools.append(ToolCallRec(
            id=f"{AGENT}:tool:{call}", session_id=sid, turn_id=turn_id,
            ts=ts, name=name, target=tool_target(inp),
            source_path=str(path), source_line=index))


def _check_rollup(row, native: str, sums: dict, out: ParsedSource) -> None:
    """Note when the session counter disagrees with message tokens."""
    roll_out = db.as_int(row["tokens_output"]) + db.as_int(
        row["tokens_reasoning"])
    msg_out = sums["output"] + sums["reasoning"]
    if msg_out and roll_out > msg_out * 2:
        out.errors.append(
            f"session {native} output rollup {roll_out} is larger than "
            f"message tokens {msg_out}; report uses message tokens")
