"""End-to-end: collect -> tasks -> snapshot, incrementality, accounting."""

import json
from datetime import UTC, datetime

from fixtures.builders import SID, build_claude, build_cursor

from tuner import config
from tuner.collect import collect
from tuner.collectors import build_collectors
from tuner.reports.periods import Period
from tuner.reports.snapshot import build_snapshot

U8 = "utf-8"

CUR = "cursor:22222222-aaaa-bbbb-cccc-000000000002"


def run(conn, **kw):
    cfg = config.load()
    return collect(conn, build_collectors(cfg), cfg, **kw)


def period():
    return Period("t", datetime(2026, 10, 1, tzinfo=UTC),
                  datetime(2026, 11, 1, tzinfo=UTC), "UTC")


def counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("sessions", "turns", "usage_events", "tool_calls",
                      "events", "tasks")}


def test_incremental_and_idempotent(env, conn):
    build_claude(env)
    first = run(conn)
    assert first.parsed == 2 and first.failed == 0
    before = counts(conn)
    second = run(conn)
    assert second.parsed == 0 and second.skipped == 2
    assert counts(conn) == before
    third = run(conn, full=True)  # forced reparse must not duplicate
    assert third.parsed == 2
    assert counts(conn) == before


def test_changed_file_is_reparsed_without_duplicates(env, conn):
    files = build_claude(env)
    run(conn)
    before = counts(conn)
    with open(files["main"], "a", encoding=U8) as fh:
        fh.write("\n")  # fingerprint changes, content equal
    stats = run(conn)
    assert stats.parsed == 1
    assert counts(conn) == before


def test_resumed_session_replay_not_double_counted(env, conn):
    files = build_claude(env)
    run(conn)
    base = conn.execute("SELECT SUM(output_tokens) FROM usage_events"
                        ).fetchone()[0]
    replay = files["main"].with_name("replayed-session.jsonl")
    replay.write_text(files["main"].read_text(U8), U8)
    run(conn)
    after = conn.execute("SELECT SUM(output_tokens) FROM usage_events"
                         ).fetchone()[0]
    assert after == base


def test_every_prompt_is_a_task_and_followups_are_linked(env, conn):
    build_claude(env)
    run(conn)
    rows = conn.execute("SELECT id, title, boundary, confidence, "
                        "evidence_json FROM tasks ORDER BY started_at"
                        ).fetchall()
    assert len(rows) == 3  # nothing is merged
    assert {r["boundary"] for r in rows} == {"new_prompt"}
    ev = [json.loads(r["evidence_json"]) for r in rows]
    # "yes" (short, 5 min later) continues task 1; the 18:00 long prompt
    # starts a new thread
    assert ev[1]["continues"]["task_id"] == rows[0]["id"]
    assert ev[1]["continues"]["rule"] == "affirmation"
    assert ev[1]["thread_id"] == ev[0]["thread_id"] == rows[0]["id"]
    assert ev[2]["continues"] is None
    assert ev[2]["thread_id"] == rows[2]["id"]


def test_subagent_usage_attributed_to_parent_task(env, conn):
    build_claude(env)
    run(conn)
    snap = build_snapshot(conn, config.load(), period())
    first = snap["tasks"][0]
    assert first["subagents"]["count"] == 1
    assert first["subagents"]["tokens"] == 7 + 70 + 700
    models = {m["model"] for m in first["models"]}
    assert models == {"claude-sonnet-4-5", "claude-haiku-4-5"}
    rec = snap["data_quality"]["reconciliation"]
    assert rec["reconciled"] and rec["unattributed"] == 0
    # Task's self-reported totalTokens (999) never leaks into totals
    total = snap["overview"]["tokens"]["total"]
    expected = sum(
        r[0] for r in conn.execute(
            "SELECT input_tokens+output_tokens+cache_write_tokens+"
            "cache_read_tokens FROM usage_events"))
    assert total == expected


def test_measured_vs_estimated_never_mixed_silently(env, conn):
    build_claude(env)
    build_cursor(env)
    run(conn)
    snap = build_snapshot(conn, config.load(), period())
    by_agent = {a["agent"]: a for a in snap["overview"]["by_agent"]}
    assert by_agent["claude_code"]["measurement"] == "measured"
    assert by_agent["cursor"]["measurement"] == "estimated"
    assert snap["overview"]["quality"]["measurement"] == "mixed"
    assert any(g["code"] == "estimated_tokens"
               for g in snap["data_quality"]["coverage_gaps"])


def test_cursor_estimates_and_unlinked_subagent_reported(env, conn):
    build_cursor(env)
    run(conn)
    rows = conn.execute(
        "SELECT * FROM usage_events WHERE session_id=?", (CUR,)).fetchall()
    assert rows and all(r["measurement"] == "estimated" for r in rows)
    assert all(r["method"] == "cursor_visible_v1" for r in rows)
    snap = build_snapshot(conn, config.load(), period())
    rec = snap["data_quality"]["reconciliation"]
    # subagent transcript exists but nothing links it to a parent turn
    assert rec["unlinked_subagent_sessions"] == 1
    assert rec["unattributed"] > 0 and not rec["reconciled"]


def test_snapshot_contains_no_full_prompts_and_is_stable(env, conn):
    build_claude(env)
    run(conn)
    a = build_snapshot(conn, config.load(), period(),
                       now=datetime(2026, 11, 2, tzinfo=UTC))
    b = build_snapshot(conn, config.load(), period(),
                       now=datetime(2026, 11, 2, tzinfo=UTC))
    assert a == b
    assert a["schema_version"] == 1 and a["kind"] == "tuner.usage"
    assert a["tasks"][0]["rank"] == 1
    assert a["tasks"][0]["tokens"]["total"] >= a["tasks"][1]["tokens"]["total"]
    assert SID not in a["tasks"][0]["id"]
