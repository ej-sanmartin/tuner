"""Report handoff: notification text, inbox, and sessionStart context."""

import io
import json
from pathlib import Path

from tuner import config, handoff
from tuner.hook_spool import run_hook
from tuner.reports.generate import ReportResult
from tuner.scheduler import runner

PENDING = [{"id": "sc_a", "skill_name": "fix-tests"}]


def _usage(tasks: int) -> dict:
    return {"overview": {"counts": {"tasks": tasks},
                         "tokens": {"total": 50}}}


def test_notify_text_names_the_gap_and_the_proposals():
    missing = handoff.notify_text(1200, 4, False, 2)
    assert "Report ready, not analyzed yet. Run /tuner." in missing
    assert "2 skill proposals waiting." in missing
    ready = handoff.notify_text(10, 1, True, 0)
    assert "not analyzed" not in ready and "proposal" not in ready
    assert handoff.notify_text(10, 1, True, 1).endswith(
        "1 skill proposal waiting.")


def test_inbox_roundtrip_and_clear(env):
    handoff.publish("2026-W44", False, PENDING)
    line = handoff.agent_context()
    assert "2026-W44" in line and "sc_a" in line
    assert "Do not analyze unless they ask." in line
    assert "Do not apply unless they ask." in line
    handoff.publish("2026-W44", True, [])
    assert handoff.agent_context() is None
    assert not handoff.inbox_path().exists()


def test_other_unanalyzed_period_stays_put(env):
    handoff.publish("2026-W44", False, [])
    handoff.publish_if_current("2026-W40", True, [])
    state = handoff.load()
    assert state["period_id"] == "2026-W44"
    assert state["analysis_valid"] is False


def test_sync_pending_updates_an_existing_inbox(env):
    handoff.publish("2026-W44", False, [])
    handoff.sync_pending(PENDING)
    assert "sc_a" in handoff.agent_context()
    handoff.sync_pending([])
    assert handoff.load() is None or "sc_a" not in handoff.agent_context()


def test_session_start_injects_and_prompts_do_not(env):
    handoff.publish("2026-W44", False, PENDING)
    out = io.StringIO()
    assert run_hook("sessionStart", "{}", out) == 0
    body = json.loads(out.getvalue())
    assert "2026-W44" in body["additional_context"]
    prompt = io.StringIO()
    run_hook("beforeSubmitPrompt", "{}", prompt)
    assert json.loads(prompt.getvalue()) == {"continue": True}
    bg = io.StringIO()
    run_hook("sessionStart",
             json.dumps({"is_background_agent": True}), bg)
    assert json.loads(bg.getvalue()) == {}


def test_deliver_and_note_follow_the_report(env, conn):
    cfg = config.load()
    res = ReportResult("2026-W44", Path("."), _usage(3), "",
                       Path("r.html"), False)
    sent = []
    runner._deliver(cfg, res, lambda t, m: sent.append(m) or True,
                    lambda *a: None, 2)
    assert "not analyzed yet" in sent[0]
    assert "2 skill proposals" in sent[0]
    runner._note(conn, [res])
    assert "2026-W44" in handoff.agent_context()
    runner._note(conn, [ReportResult(
        "empty", Path("."), _usage(0), "", Path("e.html"), False)])
    assert "2026-W44" in handoff.agent_context()
