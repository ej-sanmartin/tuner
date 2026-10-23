"""Scheduler abstraction shared by launchd and Task Scheduler."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from tuner.config import DAYS
from tuner.reports import periods

# The OS also pings `schedule run` this often. It is idempotent and cheap,
# and covers calendar triggers that never fire (observed on macOS).
CHECK_INTERVAL_S = 3600


@dataclass(frozen=True)
class Spec:
    """When the OS should fire `tuner schedule run`."""

    period: str  # daily | weekly | monthly
    weekday: int  # 0=Sunday .. 6=Saturday (launchd convention)
    day_of_month: int
    hour: int
    minute: int


class Scheduler(Protocol):
    """Install, remove, and inspect the OS-level job."""

    def install(self, spec: Spec, argv: list[str]) -> str: ...
    def uninstall(self) -> bool: ...
    def status(self) -> dict: ...


def local_spec(period: str, day: str, time_text: str, tz: str,
               now: datetime | None = None) -> Spec:
    """Translate config (possibly another timezone) to local wall time.

    The OS scheduler always fires in local time. For tz == "local" this is
    exact and DST-safe; for other zones we convert the next trigger once
    (the idempotent `schedule run` still anchors periods to `tz`).
    """
    now = now or datetime.now(UTC)
    wall = periods.to_wall(now, tz)
    trig = periods.latest_trigger(wall, period, day, time_text)
    trig = periods.next_trigger(trig, period)
    local = periods.to_wall(periods.to_utc(trig, tz), "local")
    weekday = (local.weekday() + 1) % 7  # Python Mon=0 -> Sunday=0
    if tz == "local" and period == "weekly":
        weekday = (DAYS.index(day) + 1) % 7
    return Spec(period, weekday, local.day if tz != "local" else 1,
                local.hour, local.minute)


def get_scheduler() -> Scheduler:
    """Scheduler implementation for this platform."""
    if sys.platform == "darwin":
        from tuner.scheduler.macos import LaunchdScheduler
        return LaunchdScheduler()
    if sys.platform == "win32":
        from tuner.scheduler.windows import WindowsScheduler
        return WindowsScheduler()
    from tuner.scheduler.unsupported import UnsupportedScheduler
    return UnsupportedScheduler()
