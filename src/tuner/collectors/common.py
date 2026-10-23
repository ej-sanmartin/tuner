"""Helpers shared by collectors."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tuner.security.redact import preview

_REPO_CACHE: dict[str, tuple[str, str]] = {}


def iso_utc(value: Any) -> str | None:
    """Normalise an ISO string or epoch (s/ms) to UTC `...Z`; else None."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 1e11 else value
            dt = datetime.fromtimestamp(seconds, UTC)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    except (ValueError, OverflowError, OSError):
        return None


def repo_for(path: str | None) -> tuple[str | None, str | None]:
    """Return (repo_root, repo_name) for a working directory.

    Walks up looking for `.git`; falls back to the path itself. Purely a
    stat-based heuristic, so it also works for paths that no longer exist.
    """
    if not path:
        return None, None
    hit = _REPO_CACHE.get(path)
    if hit:
        return hit
    root = Path(path)
    for cand in [root, *list(root.parents)[:12]]:
        try:
            if (cand / ".git").exists():
                root = cand
                break
        except OSError:
            break
    result = (str(root), root.name or str(root))
    _REPO_CACHE[path] = result
    return result


_TARGET_KEYS = ("file_path", "path", "notebook_path", "target_file",
                "command", "pattern", "glob_pattern", "url", "query",
                "skill", "name", "subagent_type", "description")


def tool_target(inp: Any, limit: int = 160) -> str:
    """Short redacted description of what a tool call operated on."""
    if not isinstance(inp, dict):
        return ""
    for key in _TARGET_KEYS:
        val = inp.get(key)
        if isinstance(val, str) and val:
            return preview(val, limit)
    return ""


_USER_QUERY = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.S)


def strip_wrappers(text: str) -> str:
    """Remove Cursor's <user_query> wrapper and similar envelopes."""
    m = _USER_QUERY.search(text)
    return m.group(1) if m else text


def estimate_tokens(chars: int) -> int:
    """Documented heuristic: ~4 characters per token (rounded up)."""
    return (chars + 3) // 4
