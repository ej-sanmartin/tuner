"""Open WebUI collector: measured tokens in webui.db.

Usage lives on assistant rows in `chat_message.usage`. The `chat.chat`
JSON blob is the same conversation and is not read again.
"""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from tuner import paths
from tuner.collectors import local_db as db
from tuner.collectors.base import SourceFile
from tuner.collectors.common import iso_utc
from tuner.models import ParsedSource, SessionRec, TurnRec
from tuner.security.redact import compile_extra, preview

AGENT = "open_webui"


def candidate_dbs(extra: list[str] | None = None) -> list[Path]:
    """Open WebUI database files that exist."""
    home = paths.user_home()
    cands = [home / ".open-webui" / "webui.db"]
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        cands.append(Path(xdg) / "open-webui" / "webui.db")
    cands += [Path(p) for p in extra or []]
    return db.existing(cands)


def _tokens(raw: object) -> dict | None:
    """Normalized token counts from a usage JSON value."""
    data = db.parse_json(raw)
    if not isinstance(data, dict):
        return None
    incoming = data.get("input_tokens")
    if incoming is None:
        incoming = data.get("prompt_tokens", data.get("prompt_eval_count"))
    outgoing = data.get("output_tokens")
    if outgoing is None:
        outgoing = data.get("completion_tokens", data.get("eval_count"))
    if incoming is None and outgoing is None:
        return None
    return {"input": incoming, "output": outgoing, "reasoning": 0,
            "cache_read": 0, "cache_write": 0}


class OpenWebUICollector:
    """Reads `webui.db`."""

    name = AGENT
    optional = True

    def __init__(self, extra_dbs: list[str] | None = None,
                 redact_patterns: list[str] | None = None) -> None:
        self.extra_dbs = extra_dbs or []
        self.extra = compile_extra(redact_patterns or [])

    def discover(self) -> bool:
        """True when a webui.db exists."""
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
                       "cache_write": "unavailable",
                       "cache_read": "unavailable"},
            "model": "measured", "timestamps": "measured",
            "tool_calls": "unavailable", "tool_failures": "unavailable",
            "subagents": "unavailable", "compaction": "unavailable",
            "outcome": "inferred",
            "notes": ["assistant chat_message.usage; no cache split"],
        }


def _parse(conn: sqlite3.Connection, path: Path, out: ParsedSource,
           extra: list) -> None:
    """Fill `out` from one Open WebUI database."""
    if not db.has_table(conn, "chat") or not db.has_table(
            conn, "chat_message"):
        out.errors.append("webui.db has no chat_message table")
        return
    chats = db.rows(conn, out.errors, (
        "SELECT id, title, created_at, updated_at FROM chat"))
    grouped: dict[str, list] = defaultdict(list)
    for row in db.rows(conn, out.errors, (
            "SELECT id, chat_id, role, parent_id, content, model_id, "
            "usage, created_at, error FROM chat_message "
            "ORDER BY created_at")):
        grouped[row["chat_id"]].append(row)
    for chat in chats:
        _chat(chat, grouped.get(chat["id"], []), path, out, extra)


def _chat(chat, messages: list, path: Path, out: ParsedSource,
          extra: list) -> None:
    """One chat: user rows are turns, assistant usage hangs off them."""
    native = str(chat["id"])
    sid = f"{AGENT}:{native}"
    out.sessions.append(SessionRec(
        sid, AGENT, native,
        title=preview(str(chat["title"] or ""), 200, extra) or None,
        started_at=iso_utc(chat["created_at"]),
        ended_at=iso_utc(chat["updated_at"]), source_path=str(path)))
    turns: dict[str, str] = {}
    last = None
    seq = 0
    for index, msg in enumerate(messages):
        role = str(msg["role"] or "")
        ts = iso_utc(msg["created_at"])
        if role in ("user", "human"):
            text = str(msg["content"] or "")
            turn_id = f"{AGENT}:turn:{msg['id']}"
            turns[str(msg["id"])] = turn_id
            last = turn_id
            out.turns.append(TurnRec(
                turn_id, sid, seq, started_at=ts, ended_at=ts,
                prompt_preview=preview(text, 200, extra),
                prompt_chars=len(text), outcome="completed",
                source_path=str(path), source_line=index))
            seq += 1
        elif role == "assistant":
            parent = turns.get(str(msg["parent_id"] or ""))
            _assistant(msg, sid, parent or last, ts, path, index, out)


def _assistant(msg, sid, turn_id, ts, path, index, out: ParsedSource) -> None:
    """One assistant usage row, linked to its parent user turn."""
    if msg["error"] and turn_id:
        for turn in out.turns:
            if turn.id == turn_id:
                turn.outcome = "error"
    tokens = _tokens(msg["usage"])
    if tokens is None:
        return
    model = str(msg["model_id"] or "") or None
    out.usage.append(db.usage_rec(
        AGENT, str(msg["id"]), sid, turn_id, ts, model, tokens,
        "open_webui_usage", None, path, index))
