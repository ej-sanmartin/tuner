"""Fallback triggers: interval pings, activity ticks, heartbeat, doctor."""

from __future__ import annotations

import io
import plistlib
from datetime import UTC, datetime, timedelta

from tuner import config
from tuner.commands import doctor
from tuner.hook_spool import run_hook
from tuner.scheduler import runner, tick
from tuner.scheduler.base import CHECK_INTERVAL_S, Spec
from tuner.scheduler.macos import render_plist
from tuner.scheduler.windows import render_xml
from tuner.storage import repo

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def test_interval_fallback_in_both_schedulers(tmp_path):
    spec = Spec("weekly", 0, 1, 18, 0)
    plist = plistlib.loads(render_plist(spec, ["/bin/tuner"], tmp_path))
    assert plist["StartInterval"] == CHECK_INTERVAL_S
    xml = render_xml(spec, ["tuner.exe"])
    assert "<Interval>PT1H</Interval>" in xml and "TimeTrigger" in xml


def test_run_records_heartbeat_and_next_due(env, conn):
    cfg = config.load()
    runner.run_due(conn, cfg, NOW, do_collect=False,
                   notifier=lambda t, m: None, opener=lambda *a: None)
    assert repo.kv_get(conn, "last_schedule_run")
    assert not tick.is_due(NOW)  # next trigger is in the future
    assert tick.is_due(NOW + timedelta(days=8))


def test_run_on_activity_false_disables_ticks(env, conn):
    cfg = config.load()
    cfg.values["report"]["run_on_activity"] = False
    runner.run_due(conn, cfg, NOW, do_collect=False,
                   notifier=lambda t, m: None, opener=lambda *a: None)
    assert not tick.is_due(NOW + timedelta(days=400))


def test_hook_ticks_once_then_throttles(env):
    assert tick.is_due(NOW)  # no record yet
    run_hook("beforeSubmitPrompt", "{}", io.StringIO())
    assert tick.spawned == []  # only session-boundary events tick
    run_hook("sessionStart", "{}", io.StringIO())
    run_hook("stop", "{}", io.StringIO())
    assert len(tick.spawned) == 1
    assert tick.spawned[0][-2:] == ["schedule", "run"]


def test_doctor_flags_overdue_reports(env, conn):
    conn.close()
    names = {c["name"]: c for c in doctor.checks()}
    assert names["scheduled runs"]["status"] == "warn"
    assert "overdue" in names["scheduled runs"]["detail"]
