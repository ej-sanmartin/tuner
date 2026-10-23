"""Periods (DST, catch-up) and scheduler job rendering."""

import plistlib
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from tuner.reports import periods
from tuner.scheduler.base import Spec, local_spec
from tuner.scheduler.macos import render_plist
from tuner.scheduler.windows import render_xml

NY = "America/New_York"


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def due(now, done=(), tz="UTC", limit=4, catch_up=True):
    return periods.due_periods(now, "weekly", "sunday", "18:00", tz,
                               set(done), catch_up, limit)


def test_weekly_period_ids_are_trigger_dates():
    p = periods.completed_period(utc(2026, 10, 22, 12), "weekly", "sunday",
                                 "18:00", "UTC")
    assert p.id == "2026-10-18"
    assert p.start_iso.startswith("2026-10-11T18:00")


def test_periods_are_contiguous_across_dst_change():
    # US clocks go back 2026-11-01: that week is 169 hours long.
    p = periods.completed_period(utc(2026, 11, 3, 12), "weekly", "sunday",
                                 "18:00", NY)
    assert p.id == "2026-11-01"
    hours = (datetime.fromisoformat(p.end_iso.replace("Z", "+00:00")) -
             datetime.fromisoformat(p.start_iso.replace("Z", "+00:00"))
             ).total_seconds() / 3600
    assert hours == 169
    nxt = periods.completed_period(utc(2026, 11, 10, 12), "weekly",
                                   "sunday", "18:00", NY)
    assert nxt.start_iso == p.end_iso  # no gap, no overlap


def test_catch_up_generates_missing_periods_once():
    now = utc(2026, 10, 22, 12)
    assert [p.id for p in due(now)] == [
        "2026-09-27", "2026-10-04", "2026-10-11", "2026-10-18"]
    assert [p.id for p in due(now, done={"2026-10-18", "2026-10-11"})] == [
        "2026-09-27", "2026-10-04"]
    assert due(now, done={"2026-10-18"}, catch_up=False) == []
    assert len(due(now, limit=2)) == 2


def test_before_trigger_time_uses_previous_period():
    sunday_noon = utc(2026, 10, 18, 12)
    assert due(sunday_noon, limit=1)[0].id == "2026-10-11"


def test_launchd_plist_has_calendar_and_runatload(tmp_path):
    spec = Spec("weekly", 0, 1, 18, 0)
    data = plistlib.loads(render_plist(spec, ["/usr/bin/tuner"], tmp_path))
    assert data["ProgramArguments"] == ["/usr/bin/tuner", "schedule", "run"]
    assert data["StartCalendarInterval"] == {"Weekday": 0, "Hour": 18,
                                             "Minute": 0}
    assert data["RunAtLoad"] is True


def test_windows_task_xml_is_valid_and_catches_up():
    xml = render_xml(Spec("weekly", 0, 1, 18, 0),
                     [r"C:\Program Files\tuner.exe"])
    root = ET.fromstring(xml.split("?>", 1)[1])
    text = ET.tostring(root, encoding="unicode")
    assert "StartWhenAvailable>true" in text
    assert "LogonTrigger" in text and "Sunday" in text
    assert "schedule run" in text


def test_local_spec_weekly_local_timezone():
    spec = local_spec("weekly", "sunday", "18:00", "local",
                      utc(2026, 10, 22))
    assert (spec.weekday, spec.hour, spec.minute) == (0, 18, 0)


def test_scheduled_run_is_idempotent(env, conn, monkeypatch):
    from tuner import config
    from tuner.scheduler import runner
    cfg = config.load()
    sent = []
    now = utc(2026, 10, 22, 12)
    first = runner.run_due(conn, cfg, now, do_collect=False,
                           notifier=lambda t, m: sent.append(t),
                           opener=lambda *a: None)
    assert len(first) == cfg.report.backfill_limit
    second = runner.run_due(conn, cfg, now, do_collect=False,
                            notifier=lambda t, m: sent.append(t),
                            opener=lambda *a: None)
    assert second == []
    assert all(Path(r.html_path).exists() for r in first)
    assert sent == []  # empty periods do not notify
