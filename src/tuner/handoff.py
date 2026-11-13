"""Inbox for the next Cursor session and the report notification.

The scheduler and `tuner report` write a small JSON file when a report
still needs analysis or has skill proposals waiting. The sessionStart
hook reads that file (no database) and injects one line. The file is
removed when there is nothing to say.
"""

from __future__ import annotations

import json

from tuner import paths
from tuner.fsutil import atomic_write_text

_SHOWN = 8


def inbox_path():
    """Path of the handoff file."""
    return paths.data_dir() / "handoff.json"


def notify_text(tokens: int, tasks: int, analysis_valid: bool,
                pending_n: int) -> str:
    """OS notification body after a report with at least one task."""
    text = f"{tokens:,} tokens across {tasks} tasks."
    if not analysis_valid:
        text += " Report ready, not analyzed yet. Run /tuner."
    if pending_n == 1:
        text += " 1 skill proposal waiting."
    elif pending_n:
        text += f" {pending_n} skill proposals waiting."
    return text


def cli_hint(analysis_valid: bool, pending_n: int) -> str:
    """Extra line for `tuner report`, or empty when nothing is waiting."""
    parts = []
    if not analysis_valid:
        parts.append("Not analyzed yet. Run /tuner in your agent.")
    if pending_n == 1:
        parts.append("1 skill proposal waiting (`tuner skills list`).")
    elif pending_n:
        parts.append(f"{pending_n} skill proposals waiting "
                     "(`tuner skills list`).")
    return " ".join(parts)


def agent_line(period_id: str, analysis_valid: bool,
               pending: list[dict]) -> str:
    """One line for a new agent session, or empty if nothing is waiting."""
    parts = []
    if not analysis_valid and period_id:
        parts.append(
            f"Tuner report {period_id} is ready and not analyzed. "
            "Tell the user once and offer to run /tuner. "
            "Do not analyze unless they ask.")
    n = len(pending)
    if n:
        shown = pending[:_SHOWN]
        bits = [f"{p['id']} ({p.get('skill_name', '')})" for p in shown]
        extra = f" and {n - len(shown)} more" if n > len(shown) else ""
        noun = "proposal" if n == 1 else "proposals"
        parts.append(
            f"{n} skill {noun} waiting: {', '.join(bits)}{extra}. "
            "Offer `tuner skills apply ID` for each. "
            "Do not apply unless they ask.")
    return " ".join(parts)


def load() -> dict | None:
    """Read the inbox, or None if it is missing or unreadable."""
    try:
        data = json.loads(inbox_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _clear() -> None:
    """Remove the inbox. Missing files are fine."""
    try:
        inbox_path().unlink()
    except OSError:
        pass


def _slim(pending: list[dict]) -> list[dict]:
    """Keep only the fields the hook and the agent need."""
    return [{"id": p["id"], "skill_name": p.get("skill_name", "")}
            for p in pending if p.get("id")]


def publish(period_id: str, analysis_valid: bool,
            pending: list[dict]) -> None:
    """Write the inbox, or delete it when the line would be empty."""
    slim = _slim(pending)
    if not agent_line(period_id, analysis_valid, slim):
        _clear()
        return
    body = {"period_id": period_id, "analysis_valid": analysis_valid,
            "pending": slim}
    atomic_write_text(inbox_path(), json.dumps(body) + "\n")


def publish_if_current(period_id: str, analysis_valid: bool,
                       pending: list[dict]) -> None:
    """Update this period, leaving a different unanalyzed report in place."""
    state = load()
    other = bool(state) and state.get("period_id") not in (
        None, "", period_id)
    if other and not state.get("analysis_valid"):
        sync_pending(pending)
        return
    publish(period_id, analysis_valid, pending)


def sync_pending(pending: list[dict]) -> None:
    """Refresh proposals on an existing inbox."""
    state = load()
    if not state:
        return
    publish(str(state.get("period_id") or ""),
            bool(state.get("analysis_valid")), pending)


def agent_context() -> str | None:
    """Line to inject on sessionStart, or None."""
    state = load()
    if not state:
        return None
    pending = state.get("pending") or []
    if not isinstance(pending, list):
        pending = []
    line = agent_line(str(state.get("period_id") or ""),
                      bool(state.get("analysis_valid")), pending)
    return line or None
