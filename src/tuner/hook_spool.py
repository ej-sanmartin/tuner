"""Cursor hook entry point and spool reader/writer.

Kept deliberately tiny and import-light: it runs inside Cursor's agent
loop. It never reads prompts' text (only their length), never touches
SQLite, never hits the network, always exits 0, and always prints a valid
response *before* doing any I/O so Cursor can never be blocked by us.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from tuner import paths

COMMON = ("conversation_id", "generation_id", "model", "cursor_version",
          "workspace_roots", "transcript_path")
EXTRA = {
    "beforeSubmitPrompt": (),
    "stop": ("status", "loop_count"),
    "sessionStart": ("composer_mode", "is_background_agent"),
    "sessionEnd": ("reason", "duration_ms", "final_status"),
    "preCompact": ("trigger", "context_usage_percent", "context_tokens",
                   "context_window_size", "message_count",
                   "messages_to_compact", "is_first_compaction"),
    "subagentStop": ("subagent_type", "status", "duration_ms",
                     "message_count", "tool_call_count",
                     "agent_transcript_path"),
}
EVENTS = tuple(EXTRA)
RESPONSES = {"beforeSubmitPrompt": {"continue": True}}


def spool_file() -> Path:
    """Path of the append-only hook event log."""
    return paths.spool_dir() / "cursor-hooks.jsonl"


def build_record(event: str, payload: dict, now: float | None = None
                 ) -> dict | None:
    """Allow-list fields from a hook payload (no prompt/response text)."""
    if event not in EXTRA or not isinstance(payload, dict):
        return None
    rec: dict = {"ts": round(now if now is not None else time.time(), 3),
                 "event": event}
    for key in COMMON + EXTRA[event]:
        if payload.get(key) is not None:
            rec[key] = payload[key]
    if event == "beforeSubmitPrompt":
        rec["prompt_chars"] = len(str(payload.get("prompt") or ""))
    return rec


def append(rec: dict) -> None:
    """Append one JSON line using O_APPEND (atomic for small writes)."""
    path = spool_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(rec, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def run_hook(event: str, stdin_text: str, out=None) -> int:
    """Hook entry: respond immediately, then spool; swallow all errors."""
    out = out or sys.stdout
    try:
        out.write(json.dumps(RESPONSES.get(event, {})) + "\n")
        out.flush()
    except Exception:
        pass
    try:
        rec = build_record(event, json.loads(stdin_text or "{}"))
        if rec:
            append(rec)
    except Exception:
        pass  # fail open: never disturb the agent
    return 0


class HookIndex:
    """In-memory index of spooled hook events by conversation id."""

    def __init__(self, path: Path | None = None) -> None:
        self.by_conv: dict[str, list[dict]] = {}
        path = path or spool_file()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            cid = rec.get("conversation_id")
            if cid:
                self.by_conv.setdefault(str(cid), []).append(rec)
        for recs in self.by_conv.values():
            recs.sort(key=lambda r: r.get("ts", 0))

    def events(self, conv_id: str, event: str | None = None) -> list[dict]:
        """Events for a conversation, optionally filtered by name."""
        recs = self.by_conv.get(conv_id, [])
        return [r for r in recs if event is None or r["event"] == event]

    def count(self, conv_id: str) -> int:
        """Number of events (used to invalidate cached parses)."""
        return len(self.by_conv.get(conv_id, []))

    def subagent_stops(self) -> list[dict]:
        """All subagentStop events (child transcript path + parent id)."""
        return [r for recs in self.by_conv.values() for r in recs
                if r["event"] == "subagentStop"]
