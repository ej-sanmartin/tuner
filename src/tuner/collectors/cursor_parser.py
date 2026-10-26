"""Parser for Cursor agent transcripts (`agent-transcripts/**/*.jsonl`).

Observed format (verified against real files): one JSON object per line,
either `{"role": "user"|"assistant", "message": {"content": [...]}}` with
`text` / `tool_use` blocks, or `{"type": "turn_ended", "status": ...}`.
There are no timestamps, tool results, or token counts in this file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from tuner.collectors.common import strip_wrappers, tool_target
from tuner.collectors.cursor_state import head_key
from tuner.models import ToolCallRec, TurnRec
from tuner.security.redact import preview


@dataclass
class Step:
    """One model call: new context arriving, and content produced."""

    in_chars: int = 0
    out_chars: int = 0
    ts: str | None = None
    model: str | None = None
    tokens_in: int = 0  # measured, if the source ever provides them
    tokens_out: int = 0


@dataclass
class TurnDraft:
    """A turn before usage estimation and enrichment."""

    rec: TurnRec
    steps: list[Step] = field(default_factory=list)
    tools: list[ToolCallRec] = field(default_factory=list)
    head: str = ""
    method: str = "cursor_visible_v2"


def _blocks(entry: dict) -> list[dict]:
    """Content blocks of a message, tolerating unknown shapes."""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content or [] if isinstance(b, dict)]


def read_transcript(path: Path, session_id: str, extra=()
                    ) -> tuple[list[TurnDraft], int]:
    """Stream a transcript into drafts; returns (turns, bad_line_count)."""
    drafts: list[TurnDraft] = []
    bad = 0
    cur: TurnDraft | None = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if not isinstance(entry, dict):
                continue
            role = entry.get("role")
            if role == "user":
                text = strip_wrappers("\n".join(
                    str(b.get("text", "")) for b in _blocks(entry)
                    if b.get("type") == "text"))
                seq = len(drafts)
                rec = TurnRec(
                    id=f"{session_id}:turn:{seq}", session_id=session_id,
                    seq=seq, prompt_preview=preview(text, 240, extra),
                    prompt_chars=len(text), outcome="incomplete",
                    source_path=str(path), source_line=line_no)
                cur = TurnDraft(rec, [Step(in_chars=len(text))],
                                head=head_key(text))
                drafts.append(cur)
            elif role == "assistant" and cur is not None:
                _assistant(cur, entry, session_id, line_no, path)
            elif entry.get("type") == "turn_ended" and cur is not None:
                ok = entry.get("status") == "success"
                cur.rec.outcome = "completed" if ok else "error"
    return drafts, bad


def _assistant(cur: TurnDraft, entry: dict, sid: str, line_no: int,
               path: Path) -> None:
    """Add one assistant message as a step plus its tool calls."""
    out = 0
    for block in _blocks(entry):
        if block.get("type") == "text":
            out += len(str(block.get("text", "")))
        elif block.get("type") == "tool_use":
            inp = block.get("input")
            out += len(json.dumps(inp)) if inp else 0
            idx = len(cur.tools)
            cur.tools.append(ToolCallRec(
                id=f"{cur.rec.id}:tool:{idx}", session_id=sid,
                turn_id=cur.rec.id, ts=None,
                name=str(block.get("name") or "unknown"),
                target=tool_target(inp), is_error=None,
                source_path=str(path), source_line=line_no))
    pending = cur.steps[-1]  # inputs known, output now arrives
    pending.out_chars = out
    cur.steps.append(Step())
