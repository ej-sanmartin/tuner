"""Hermes collector: measured tokens in state.db.

`session_model_usage` is the category split for a whole session.
Per-message `token_count` is used only when that table is empty, so the
two are never added together.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from tuner import paths
from tuner.collectors import local_db as db
from tuner.collectors.base import SourceFile
from tuner.collectors.common import iso_utc, repo_for
from tuner.models import ParsedSource, SessionRec, ToolCallRec, TurnRec
from tuner.security.redact import compile_extra, preview

AGENT = "hermes"


def candidate_dbs(extra: list[str] | None = None) -> list[Path]:
    """Hermes state databases that exist."""
    cands = [paths.user_home() / ".hermes" / "state.db"]
    cands += [Path(p) for p in extra or []]
    return db.existing(cands)


class HermesCollector:
    """Reads `~/.hermes/state.db`."""

    name = AGENT
    optional = True

    def __init__(self, extra_dbs: list[str] | None = None,
                 redact_patterns: list[str] | None = None) -> None:
        self.extra_dbs = extra_dbs or []
        self.extra = compile_extra(redact_patterns or [])

    def discover(self) -> bool:
        """True when a Hermes state database exists."""
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
            "outcome": "unavailable",
            "notes": ["session_model_usage is one row per model for the "
                      "whole session and is attached to the last user turn",
                      "reasoning tokens are included in output"],
        }


def _parse(conn: sqlite3.Connection, path: Path, out: ParsedSource,
           extra: list) -> None:
    """Fill `out` from one Hermes database."""
    if not db.has_table(conn, "sessions"):
        out.errors.append("state.db has no sessions table")
        return
    sessions = db.rows(conn, out.errors, (
        "SELECT id, title, cwd, parent_session_id, model, started_at, "
        "ended_at, input_tokens, output_tokens, cache_read_tokens, "
        "cache_write_tokens, reasoning_tokens FROM sessions"))
    messages: dict[str, list] = defaultdict(list)
    if db.has_table(conn, "messages"):
        for row in db.rows(conn, out.errors, (
                "SELECT id, session_id, role, content, timestamp, "
                "token_count, tool_name, tool_calls FROM messages "
                "ORDER BY timestamp")):
            messages[row["session_id"]].append(row)
    usage: dict[str, list] = defaultdict(list)
    if db.has_table(conn, "session_model_usage"):
        for row in db.rows(conn, out.errors, (
                "SELECT session_id, model, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, reasoning_tokens "
                "FROM session_model_usage")):
            usage[row["session_id"]].append(row)
    for row in sessions:
        _session(row, messages.get(row["id"], []), usage.get(row["id"], []),
                 path, out, extra)


def _session(row, messages, usage_rows, path, out, extra) -> None:
    """One Hermes session."""
    native = str(row["id"])
    sid = f"{AGENT}:{native}"
    project, repo = repo_for(row["cwd"])
    meta = {}
    if row["parent_session_id"]:
        meta["parent_native_id"] = str(row["parent_session_id"])
    out.sessions.append(SessionRec(
        sid, AGENT, native, project_path=project, repo=repo,
        title=preview(str(row["title"] or ""), 200, extra) or None,
        started_at=iso_utc(row["started_at"]),
        ended_at=iso_utc(row["ended_at"]), source_path=str(path), meta=meta))
    turn_id, seq = None, 0
    message_tokens = False
    for index, msg in enumerate(messages):
        role = str(msg["role"] or "")
        ts = iso_utc(msg["timestamp"])
        if role in ("user", "human"):
            turn_id = f"{AGENT}:turn:{msg['id']}"
            text = str(msg["content"] or "")
            out.turns.append(TurnRec(
                turn_id, sid, seq, started_at=ts, ended_at=ts,
                prompt_preview=preview(text, 200, extra),
                prompt_chars=len(text), outcome="completed",
                source_path=str(path), source_line=index))
            seq += 1
            if not usage_rows and db.as_int(msg["token_count"]):
                message_tokens = True
                _message_usage(msg, sid, turn_id, ts, row["model"], path,
                               index, out, "input")
        elif role == "assistant" and not usage_rows:
            if db.as_int(msg["token_count"]):
                message_tokens = True
                _message_usage(msg, sid, turn_id, ts, row["model"], path,
                               index, out, "output")
        if role == "tool" or msg["tool_name"] or msg["tool_calls"]:
            _tools(msg, sid, turn_id, ts, path, index, out, extra)
    if usage_rows:
        _model_usage(usage_rows, sid, turn_id, path, out)
    elif not message_tokens:
        _fallback(row, sid, turn_id, path, out)


def _message_usage(msg, sid, turn_id, ts, model, path, index, out,
                   field: str) -> None:
    """One message `token_count` as input or output."""
    tokens = {"input": 0, "output": 0, "reasoning": 0,
              "cache_read": 0, "cache_write": 0}
    tokens[field] = msg["token_count"]
    out.usage.append(db.usage_rec(
        AGENT, f"msg:{msg['id']}", sid, turn_id, ts, model, tokens,
        "hermes_message", "message_token_count", path, index))


def _model_usage(rows, sid, turn_id, path, out) -> None:
    """Session-level per-model totals, on the last user turn."""
    for index, row in enumerate(rows):
        tokens = {"input": row["input_tokens"],
                  "output": row["output_tokens"],
                  "reasoning": row["reasoning_tokens"],
                  "cache_read": row["cache_read_tokens"],
                  "cache_write": row["cache_write_tokens"]}
        out.usage.append(db.usage_rec(
            AGENT, f"{sid}:{row['model']}:{index}", sid, turn_id,
            None, row["model"], tokens, "hermes_session_model_usage",
            "session_model_usage", path, index))


def _fallback(row, sid, turn_id, path, out) -> None:
    """Session columns, when no finer token table has counts."""
    tokens = {"input": row["input_tokens"], "output": row["output_tokens"],
              "reasoning": row["reasoning_tokens"],
              "cache_read": row["cache_read_tokens"],
              "cache_write": row["cache_write_tokens"]}
    if not any(db.as_int(v) for v in tokens.values()):
        return
    out.usage.append(db.usage_rec(
        AGENT, f"session:{row['id']}", sid, turn_id,
        iso_utc(row["ended_at"] or row["started_at"]), row["model"],
        tokens, "hermes_session", "session_totals", path, 0))


def _tools(msg, sid, turn_id, ts, path, index, out, extra) -> None:
    """Tool calls stored on a message."""
    calls = db.parse_json(msg["tool_calls"])
    if isinstance(calls, dict):
        calls = [calls]
    if not isinstance(calls, list) or not calls:
        name = str(msg["tool_name"] or "")
        if name:
            calls = [{"name": name}]
        else:
            return
    for nth, call in enumerate(calls):
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) \
            else {}
        name = str(call.get("name") or fn.get("name") or msg["tool_name"]
                   or "tool")
        args = fn.get("arguments", call.get("arguments"))
        target = preview(args if isinstance(args, str) else "", 160, extra)
        out.tools.append(ToolCallRec(
            id=f"{AGENT}:tool:{msg['id']}:{nth}", session_id=sid,
            turn_id=turn_id, ts=ts, name=name, target=target,
            source_path=str(path), source_line=index))
