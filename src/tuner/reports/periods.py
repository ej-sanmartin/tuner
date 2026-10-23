"""Reporting periods anchored to wall-clock schedule triggers.

All arithmetic is done on naive *wall-clock* datetimes in the configured
timezone and converted to UTC only at the edges. That keeps "Sunday 18:00"
correct across daylight-saving changes (a weekly period may be 167 or 169
hours long) and keeps delayed runs anchored to their intended interval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from tuner.config import DAYS

ISO = "%Y-%m-%dT%H:%M:%S.%f"


@dataclass(frozen=True)
class Period:
    """A half-open reporting interval [start, end) in UTC."""

    id: str
    start: datetime
    end: datetime
    timezone: str
    partial: bool = False

    @staticmethod
    def fmt(dt: datetime) -> str:
        """UTC ISO string comparable with stored timestamps."""
        return dt.astimezone(UTC).strftime(ISO)[:-3] + "Z"

    @property
    def start_iso(self) -> str:
        """Start as UTC ISO string."""
        return self.fmt(self.start)

    @property
    def end_iso(self) -> str:
        """End as UTC ISO string."""
        return self.fmt(self.end)


def to_utc(wall: datetime, tz: str) -> datetime:
    """Interpret naive `wall` in `tz` ('local' = system zone) as UTC."""
    if tz == "local":
        return wall.astimezone(UTC)
    return wall.replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)


def to_wall(utc: datetime, tz: str) -> datetime:
    """Convert an aware datetime to naive wall-clock time in `tz`."""
    zone = None if tz == "local" else ZoneInfo(tz)
    return utc.astimezone(zone).replace(tzinfo=None)


def _hm(time_text: str) -> tuple[int, int]:
    """Parse 'HH:MM'."""
    h, m = time_text.split(":")
    return int(h), int(m)


def latest_trigger(now_wall: datetime, period: str, day: str,
                   time_text: str) -> datetime:
    """Most recent scheduled trigger at or before `now_wall` (wall time)."""
    h, m = _hm(time_text)
    today = now_wall.replace(hour=h, minute=m, second=0, microsecond=0)
    if period == "daily":
        return today if today <= now_wall else today - timedelta(days=1)
    if period == "weekly":
        back = (now_wall.weekday() - DAYS.index(day)) % 7
        cand = today - timedelta(days=back)
        return cand if cand <= now_wall else cand - timedelta(days=7)
    first = today.replace(day=1)
    if first <= now_wall:
        return first
    prev = first - timedelta(days=1)
    return prev.replace(day=1)


def previous_trigger(trigger: datetime, period: str) -> datetime:
    """The trigger one period before `trigger` (wall time)."""
    if period == "daily":
        return trigger - timedelta(days=1)
    if period == "weekly":
        return trigger - timedelta(days=7)
    return (trigger.replace(day=1) - timedelta(days=1)).replace(day=1)


def next_trigger(trigger: datetime, period: str) -> datetime:
    """The trigger one period after `trigger` (wall time)."""
    if period == "daily":
        return trigger + timedelta(days=1)
    if period == "weekly":
        return trigger + timedelta(days=7)
    return (trigger.replace(day=28) + timedelta(days=4)).replace(day=1)


def period_for_trigger(trigger: datetime, period: str, tz: str,
                       partial: bool = False) -> Period:
    """Period ending at `trigger` (wall time); id is the trigger date."""
    start = previous_trigger(trigger, period)
    pid = trigger.strftime("%Y-%m-%d")
    return Period(pid + ("-to-date" if partial else ""),
                  to_utc(start, tz), to_utc(trigger, tz), tz, partial)


def completed_period(now: datetime, period: str, day: str, time_text: str,
                     tz: str) -> Period:
    """The latest fully completed period as of `now` (aware)."""
    trig = latest_trigger(to_wall(now, tz), period, day, time_text)
    return period_for_trigger(trig, period, tz)


def current_period(now: datetime, period: str, day: str, time_text: str,
                   tz: str) -> Period:
    """The in-progress period, ending at the next trigger (partial)."""
    trig = latest_trigger(to_wall(now, tz), period, day, time_text)
    return period_for_trigger(next_trigger(trig, period), period, tz, True)


def due_periods(now: datetime, period: str, day: str, time_text: str,
                tz: str, done_ids: set[str], catch_up: bool,
                backfill_limit: int) -> list[Period]:
    """Completed periods not yet generated, oldest first.

    Without catch-up only the latest period is considered. With catch-up
    at most `backfill_limit` of the most recent missing periods are
    returned (never duplicates of `done_ids`).
    """
    trig = latest_trigger(to_wall(now, tz), period, day, time_text)
    horizon = max(1, backfill_limit) if catch_up else 1
    due: list[Period] = []
    for _ in range(horizon):
        p = period_for_trigger(trig, period, tz)
        if p.id not in done_ids:
            due.append(p)
        trig = previous_trigger(trig, period)
    return list(reversed(due))
