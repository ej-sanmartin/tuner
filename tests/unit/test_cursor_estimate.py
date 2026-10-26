"""Cursor estimator: fitted context model, caps and compaction restart."""

import math

from tuner.collectors.cursor_estimate import (
    OUTPUT_FACTOR,
    RESULT_CAP_TOKENS,
    SYSTEM_TOKENS,
    WINDOW_TOKENS,
    estimate_usage,
)
from tuner.collectors.cursor_parser import Step, TurnDraft
from tuner.models import TurnRec


def _draft(seq, steps):
    rec = TurnRec(id=f"t{seq}", session_id="s", seq=seq, started_at=None,
                  ended_at=None, prompt_preview="p", prompt_chars=4,
                  outcome="completed", source_line=seq)
    return TurnDraft(rec=rec, steps=steps, method="cursor_bubbles_v1")


def _step(ts, in_chars=400, out_chars=400):
    return Step(in_chars=in_chars, out_chars=out_chars, ts=ts)


def _est(steps, compactions=None):
    return estimate_usage([_draft(0, steps)], "s", "m", "p", "src",
                          compactions)


def test_first_step_writes_the_context_later_steps_read_it():
    usage = _est([_step("2026-10-26T01:00:00.000Z")] * 2)
    assert usage[0].input_tokens == SYSTEM_TOKENS
    assert usage[0].cache_read_tokens == 0
    # step 2: context = system + 100 in + 100 out; new = result + output
    assert usage[1].input_tokens == 200
    assert usage[1].cache_read_tokens == SYSTEM_TOKENS


def test_output_is_scaled_for_hidden_reasoning():
    usage = _est([_step("2026-10-26T01:00:00.000Z")])
    assert usage[0].output_tokens == math.ceil(100 * OUTPUT_FACTOR)


def test_tool_results_are_capped_but_the_prompt_is_not():
    big = 4 * 10 * RESULT_CAP_TOKENS
    usage = _est([_step("2026-10-26T01:00:00.000Z", big, 0),
                  _step("2026-10-26T01:00:01.000Z", big, 0),
                  _step("2026-10-26T01:00:02.000Z", 0, 0)])
    # prompt (10x cap) is kept in full; the 2nd step's result is cut
    want = SYSTEM_TOKENS + 10 * RESULT_CAP_TOKENS + RESULT_CAP_TOKENS
    assert usage[2].input_tokens + usage[2].cache_read_tokens == want


def test_context_restarts_after_a_compaction():
    steps = [_step("2026-10-26T01:00:00.000Z"),
             _step("2026-10-26T02:00:00.000Z"),
             _step("2026-10-26T03:00:00.000Z")]
    cut = _est(steps, ["2026-10-26T01:30:00.000Z"])
    ctx = [u.input_tokens + u.cache_read_tokens for u in cut]
    assert ctx[1] == SYSTEM_TOKENS  # restarted before the 2nd step
    assert ctx[2] > SYSTEM_TOKENS


def test_context_is_capped_at_the_window():
    big = _step("2026-10-26T01:00:00.000Z", in_chars=4 * WINDOW_TOKENS)
    usage = _est([big, big, big])
    assert max(u.input_tokens + u.cache_read_tokens
               for u in usage) == WINDOW_TOKENS
