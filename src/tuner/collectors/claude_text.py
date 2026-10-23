"""Text helpers for Claude Code transcript entries."""

from __future__ import annotations

import re
from typing import Any

CMD = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
ARGS = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.S)
META_PREFIXES = ("<local-command-", "Caveat:", "<system-reminder>")


def text_of(content: Any) -> tuple[str, bool]:
    """Return (human text, has_tool_result) for a user message body."""
    if isinstance(content, str):
        return content, False
    texts, has_result = [], False
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            has_result = True
        elif block.get("type") == "text":
            texts.append(str(block.get("text", "")))
    return "\n".join(texts), has_result


def result_text(block: dict) -> str:
    """Flatten a tool_result block's content to text."""
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text", "")) for b in content
                        if isinstance(b, dict))
    return ""
