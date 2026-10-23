"""Activity-triggered catch-up: a cheap, throttled `schedule run` spawn.

OS timers can be missed (asleep, off, or simply never fired). Agent
activity is a second, independent trigger: Cursor hooks call
`maybe_tick`, which compares now against a one-line `next_due` file and,
if due, starts a detached `tuner schedule run`. Kept import-light because
it runs inside the hook path; it never raises and never waits.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta

from tuner import paths
from tuner.fsutil import atomic_write_text

THROTTLE = timedelta(minutes=15)
NEVER = "9999-12-31T00:00:00+00:00"


def next_due_file():
    """Path of the file holding the next time a run is worthwhile."""
    return paths.data_dir() / "next_due"


def write_next_due(when: datetime | None) -> None:
    """Record the next due time (None disables activity ticks)."""
    text = when.astimezone(UTC).isoformat() if when else NEVER
    atomic_write_text(next_due_file(), text + "\n")


def is_due(now: datetime | None = None) -> bool:
    """True if there is no record yet or the recorded time has passed."""
    now = now or datetime.now(UTC)
    try:
        raw = next_due_file().read_text(encoding="utf-8").strip()
        return now >= datetime.fromisoformat(raw)
    except (OSError, ValueError):
        return True


def _popen(argv: list[str]) -> None:
    """Start a fully detached process (patched in tests)."""
    kwargs: dict = {"stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":  # DETACHED | NEW_GROUP | NO_WINDOW
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)  # noqa: S603


def maybe_tick(now: datetime | None = None) -> bool:
    """Spawn `tuner schedule run` if due; returns True if spawned."""
    now = now or datetime.now(UTC)
    if not is_due(now):
        return False
    from tuner.integrations.exe import tuner_argv
    write_next_due(now + THROTTLE)  # stop concurrent hooks stampeding
    _popen([*tuner_argv(), "schedule", "run"])
    return True
