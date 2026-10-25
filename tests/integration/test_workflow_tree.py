"""Workflow tree: task -> subagents, continuation links, regrouping."""

from datetime import UTC, datetime

from fixtures.builders import build_claude

from tuner import config
from tuner.attribution.tasks import group_turns
from tuner.collect import collect
from tuner.collectors import build_collectors
from tuner.reports.periods import Period
from tuner.reports.snapshot import build_snapshot
from tuner.storage import repo


def _run(conn):
    cfg = config.load()
    return collect(conn, build_collectors(cfg), cfg)


def _snap(conn):
    p = Period("t", datetime(2026, 10, 1, tzinfo=UTC),
               datetime(2026, 11, 1, tzinfo=UTC), "UTC")
    return build_snapshot(conn, config.load(), p)


def test_subagent_is_listed_under_the_task_that_spawned_it(env, conn):
    build_claude(env)
    _run(conn)
    first = _snap(conn)["tasks"][0]["subagents"]
    assert first["count"] == 1 and first["omitted"] == 0
    node = first["items"][0]
    assert node["description"] == "explore"
    assert node["tokens"]["total"] == first["tokens"] == 7 + 70 + 700
    assert node["models"] == ["claude-haiku-4-5"]
    assert node["quality"]["measurement"] == "measured"
    assert node["linked"] and node["spawned_by_turn"]
    assert first["own_tokens"] > 0  # parent's own work stays separate


def test_other_tasks_have_no_subagents(env, conn):
    build_claude(env)
    _run(conn)
    others = [t for t in _snap(conn)["tasks"] if t["subagents"]["count"] == 0]
    assert len(others) == 2 and all(
        t["subagents"]["items"] == [] for t in others)


def test_grouping_is_redone_when_the_rules_change(env, conn):
    build_claude(env)
    _run(conn)
    rules = repo.kv_get(conn, "attribution_rules")
    repo.kv_set(conn, "attribution_rules", "1:old")
    conn.execute("DELETE FROM tasks")
    conn.execute("DELETE FROM task_turns")
    conn.commit()
    _run(conn)  # no file changed, but grouping rules did
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 3
    assert repo.kv_get(conn, "attribution_rules") == rules
    _run(conn)  # unchanged rules: nothing to redo
    assert _run(conn).tasks_written == 0


def _turn(i, start, end, chars, outcome):
    return {"id": i, "started_at": start, "ended_at": end,
            "prompt_chars": chars, "prompt_preview": i, "outcome": outcome}


def test_interrupted_turn_links_even_a_long_followup():
    rows = [
        _turn("a", "2026-10-12T10:00:00Z", "2026-10-12T10:01:00Z", 500,
              "interrupted"),
        _turn("b", "2026-10-12T10:05:00Z", "2026-10-12T10:06:00Z", 500,
              "completed"),
        _turn("c", "2026-10-12T12:00:00Z", "2026-10-12T12:01:00Z", 5,
              "completed")]
    a, b, c = group_turns("s", rows, True, 80, 30)
    assert b.continues["rule"] == "interrupted_previous"
    assert b.thread_id == a.id
    assert c.continues is None  # short, but 114 minutes later
    assert group_turns("s", rows, False, 80, 30)[1].continues is None
