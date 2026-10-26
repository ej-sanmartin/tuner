"""Per-turn model comes from the prompt hook, not the chat's current one."""

from tuner.collectors.cursor_enrich import apply_hook_models
from tuner.collectors.cursor_parser import Step, TurnDraft
from tuner.models import TurnRec


def _draft(seq, started_at):
    rec = TurnRec(id=f"t{seq}", session_id="s", seq=seq,
                  started_at=started_at, ended_at=None, prompt_preview="p",
                  prompt_chars=4, outcome="completed", source_line=seq)
    return TurnDraft(rec=rec, steps=[Step(model="grok-4.7")])


def _prompt(ts, model):
    return {"event": "beforeSubmitPrompt", "ts": ts, "model": model}


def test_turns_get_the_model_their_prompt_used():
    # 1792988800 == 2026-10-26T04:26:40Z
    a = _draft(0, "2026-10-26T04:26:40.500Z")
    b = _draft(1, "2026-10-26T04:36:40.100Z")
    events = [_prompt(1792988800.0, "claude-sonnet-5-5-high"),
              _prompt(1792989400.0, "grok-4.7-high-fast")]
    assert apply_hook_models([a, b], events) == 2
    assert a.steps[0].model == "claude-sonnet-5-5"
    assert b.steps[0].model == "grok-4.7"


def test_unmatched_turns_keep_their_model():
    d = _draft(0, "2026-10-26T04:26:40.000Z")
    events = [_prompt(1792988900.0, "claude-sonnet-5-5-high")]  # 100 s off
    assert apply_hook_models([d], events) == 0
    assert d.steps[0].model == "grok-4.7"
