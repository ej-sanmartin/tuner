"""Read bounded, redacted text excerpts from local transcripts on demand.

The database stores only short previews. When an agent analyses a task it
may need the full prompt and the final answer; we re-read just those lines
from the source transcript, redact, truncate, and never persist them.
"""

from __future__ import annotations

import json
from itertools import islice
from pathlib import Path

from tuner.collectors.common import strip_wrappers
from tuner.security.redact import redact

MAX_SCAN_LINES = 20_000


def _blocks(obj: dict) -> tuple[str, str, bool]:
    """(role, joined text, has_tool_result) of one transcript record."""
    msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    role = obj.get("role") or msg.get("role") or obj.get("type") or ""
    content = msg.get("content", obj.get("content"))
    if isinstance(content, str):
        return role, content, False
    texts, tool_result = [], False
    for part in content or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            texts.append(str(part.get("text", "")))
        elif part.get("type") == "tool_result":
            tool_result = True
    return role, "\n".join(texts), tool_result


def _clip(text: str, limit: int) -> str:
    """Redact and truncate (keeping the head and tail)."""
    text = redact(text.strip())
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[... {len(text) - limit} chars omitted ...]\n" \
           f"{text[-half:]}"


def _line(path: Path, number: int) -> dict | None:
    """Parse the 1-based line `number` of a JSONL file."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            raw = next(islice(fh, number - 1, number), None)
        return json.loads(raw) if raw else None
    except (OSError, ValueError):
        return None


def prompt_text(source_path: str, line: int, limit: int = 1500) -> str:
    """Full (redacted, clipped) user prompt at a transcript line."""
    obj = _line(Path(source_path), line)
    if not obj:
        return ""
    role, text, _ = _blocks(obj)
    return _clip(strip_wrappers(text), limit) if role == "user" else ""


def final_response(source_path: str, line: int, limit: int = 800) -> str:
    """Last assistant text before the next real user prompt."""
    last = ""
    try:
        with Path(source_path).open(encoding="utf-8",
                                    errors="replace") as fh:
            for raw in islice(fh, line, line + MAX_SCAN_LINES):
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                role, text, tool_result = _blocks(obj)
                if role == "user" and text.strip() and not tool_result:
                    break
                if role == "assistant" and text.strip():
                    last = text
    except OSError:
        return ""
    return _clip(last, limit) if last else ""
