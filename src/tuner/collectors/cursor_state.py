"""Optional, read-only enrichment from Cursor's internal state DB.

`state.vscdb` is undocumented and may change, so every access is
defensive: failures simply mean "no enrichment" and are surfaced as
coverage gaps. We never write to it and open it read-only so we cannot
interfere with a running Cursor. Only key-range lookups are used
(indexed), never full scans.

Verified locally: `tokenCount` exists on bubbles but is currently always
zero; timestamps, model names, thinking text and tool results are present.
If Cursor starts populating `tokenCount`, it is used as MEASURED data.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tuner.collectors.common import iso_utc


@dataclass
class Bubble:
    """One chat bubble (user or assistant) with size/time metadata."""

    kind: int  # 1 = user, 2 = assistant
    ts: str | None
    model: str | None
    text_chars: int = 0
    text_head: str = ""  # normalised prefix, user bubbles only
    thinking_chars: int = 0
    args_chars: int = 0
    result_chars: int = 0
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_status: str | None = None
    spawn_tool_call_id: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class Composer:
    """Conversation-level metadata plus ordered bubbles."""

    model: str | None = None
    created_ms: int | None = None
    subagent_ids: list[str] = field(default_factory=list)
    bubbles: list[Bubble] = field(default_factory=list)


def _clen(value: Any) -> int:
    """Character length of a text-like or JSON-like value."""
    if not value:
        return 0
    if isinstance(value, str):
        return len(value)
    try:
        return len(json.dumps(value))
    except (TypeError, ValueError):
        return 0


def head_key(text: object) -> str:
    """Normalised 50-char prefix used to align prompts across sources."""
    return " ".join(str(text or "").split())[:50].lower()


def _bubble(d: dict) -> Bubble:
    """Convert one raw bubble dict (tolerating missing fields)."""
    tf = d.get("toolFormerData") or {}
    tc = d.get("tokenCount") or {}
    thinking = d.get("thinking")
    kind = int(d.get("type") or 0)
    return Bubble(
        kind=kind,
        text_head=head_key(d.get("text")) if kind == 1 else "",
        ts=iso_utc(d.get("createdAt")),
        model=(d.get("modelInfo") or {}).get("modelName"),
        text_chars=_clen(d.get("text")),
        thinking_chars=_clen(thinking.get("text")
                             if isinstance(thinking, dict) else thinking),
        args_chars=_clen(tf.get("rawArgs") or tf.get("params")),
        result_chars=_clen(tf.get("result")),
        tool_call_id=tf.get("toolCallId"), tool_name=tf.get("name"),
        tool_status=tf.get("status"),
        spawn_tool_call_id=d.get("subagentSpawnTaskToolCallId"),
        tokens_in=int(tc.get("inputTokens") or 0),
        tokens_out=int(tc.get("outputTokens") or 0))


class CursorState:
    """Read-only handle on `state.vscdb`; `available` is False on error."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.error: str | None = None
        self._conn: sqlite3.Connection | None = None
        if not path.exists():
            self.error = "state database not found"
            return
        # Prefer a normal read-only open (sees the WAL, consistent while
        # Cursor is running); fall back to immutable if it is unreadable.
        for flags in ("mode=ro", "mode=ro&immutable=1"):
            try:
                conn = sqlite3.connect(f"file:{path.as_posix()}?{flags}",
                                       uri=True, timeout=2)
                conn.execute("SELECT 1 FROM cursorDiskKV LIMIT 1")
                self._conn = conn
                return
            except sqlite3.Error as exc:
                self.error = f"cannot open state database: {exc}"

    @property
    def available(self) -> bool:
        """True when the DB opened successfully."""
        return self._conn is not None

    def close(self) -> None:
        """Close the connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def composer(self, composer_id: str) -> Composer | None:
        """Load metadata and bubbles for one conversation, or None."""
        if self._conn is None:
            return None
        try:
            return self._load(composer_id)
        except (sqlite3.Error, ValueError, TypeError) as exc:
            self.error = f"state database read failed: {exc}"
            return None

    def _load(self, cid: str) -> Composer | None:
        """Query composerData and bubbles via indexed key ranges."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM cursorDiskKV WHERE key=?",
            (f"composerData:{cid}",)).fetchone()
        if row is None:
            return None
        meta = json.loads(row[0])
        order = [h.get("bubbleId") for h in
                 meta.get("fullConversationHeadersOnly") or []]
        lo, hi = f"bubbleId:{cid}:", f"bubbleId:{cid};"
        raw: dict[str, dict] = {}
        for key, val in self._conn.execute(
                "SELECT key, value FROM cursorDiskKV WHERE key>=? AND key<?",
                (lo, hi)):
            try:
                raw[key[len(lo):]] = json.loads(val)
            except (ValueError, TypeError):
                continue
        ids = [b for b in order if b in raw] or sorted(
            raw, key=lambda b: str(raw[b].get("createdAt")))
        cfg = meta.get("modelConfig") or {}
        return Composer(
            model=cfg.get("modelName"), created_ms=meta.get("createdAt"),
            subagent_ids=[str(s) for s in
                          meta.get("subagentComposerIds") or []],
            bubbles=[_bubble(raw[b]) for b in ids])
