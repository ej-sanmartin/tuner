"""`tuner analyze next` is one read for the agent."""

import json
from datetime import UTC, datetime

import pytest
from fixtures.builders import build_claude

from tuner import config, handoff
from tuner.analysis import service
from tuner.analysis.validate import AnalysisError
from tuner.collect import collect
from tuner.collectors import build_collectors
from tuner.commands.analyze import _next
from tuner.reports import generate as gen
from tuner.reports.periods import Period

GOOD = """---
name: fix-tests
description: Run and fix failing parser tests quickly. Use for test failures.
---

# Fix tests

Run the failing test first, then fix.
"""


def _plan(env, conn):
    """Collect a fixture session and build its analysis plan."""
    build_claude(env)
    cfg = config.load()
    collect(conn, build_collectors(cfg), cfg)
    period = Period("t", datetime(2026, 10, 1, tzinfo=UTC),
                    datetime(2026, 11, 1, tzinfo=UTC), "UTC")
    gen.generate(conn, cfg, period, now=datetime(2026, 11, 2, tzinfo=UTC))
    return cfg, service.make_plan(conn, cfg, gen.report_dir("t"))


def _doc(plan) -> dict:
    """Minimal valid analysis that proposes one skill."""
    tid = plan.selection[0]
    return {"cache_key": plan.key, "tasks": [{
        "task_id": tid, "title": "Fix the failing test",
        "objective": "fix a test", "summary": "ok",
        "classification": {"productive_complexity": ["real work"]}}],
        "recommendations": [{
            "title": "Add a test-fix skill", "kind": "skill",
            "scope": "global", "confidence": "medium",
            "description": "Capture the loop",
            "evidence": [{"task_id": tid, "claim": "tool calls",
                          "refs": ["P1"]}],
            "skill_change": {"name": "fix-tests", "content": GOOD}}]}


def test_next_then_save_surfaces_the_proposal(env, conn, capsys):
    cfg, plan = _plan(env, conn)
    _next(conn, cfg, plan)
    missing = json.loads(capsys.readouterr().out)
    assert missing["status"] == "missing"
    assert missing["evidence"]["cache_key"] == plan.key
    assert "tasks" in missing["schema"]
    service.save_analysis(conn, cfg, plan, _doc(plan), {"agent": "test"})
    line = handoff.agent_context()
    assert "not analyzed" not in line
    assert "fix-tests" in line
    _next(conn, cfg, plan)
    saved = json.loads(capsys.readouterr().out)
    assert saved["status"] == "valid"
    assert saved["pending_skills"][0]["skill_name"] == "fix-tests"
    assert saved["pending_skills"][0]["apply"].startswith(
        "tuner skills apply ")
    assert saved["analysis"]["tasks"][0]["title"] == "Fix the failing test"


def test_task_title_is_required_and_at_most_80_chars(env, conn):
    cfg, plan = _plan(env, conn)
    missing = _doc(plan)
    del missing["tasks"][0]["title"]
    with pytest.raises(AnalysisError, match="title: required"):
        service.save_analysis(conn, cfg, plan, missing, {"agent": "test"})
    long = _doc(plan)
    long["tasks"][0]["title"] = "x" * 81
    with pytest.raises(AnalysisError, match="80 characters"):
        service.save_analysis(conn, cfg, plan, long, {"agent": "test"})
