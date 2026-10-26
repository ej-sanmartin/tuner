"""Cursor estimator v2: context restarts at compaction and is capped."""

from tuner.collectors.cursor_estimate import WINDOW_TOKENS, estimate_usage
from tuner.collectors.cursor_parser import Step, TurnDraft
from tuner.models import TurnRec


def _draft(seq, steps):
    rec = TurnRec(id=f"t{seq}", session_id="s", seq=seq, started_at=None,
                  ended_at=None, prompt_preview="p", prompt_chars=4,
                  outcome="completed", source_line=seq)
    return TurnDraft(rec=rec, steps=steps, method="cursor_bubbles_v2")


def _step(ts, chars=400):
    return Step(in_chars=chars, out_chars=chars, ts=ts)


def _reads(usage):
    return [u.cache_read_tokens for u in usage]


def test_context_restarts_after_a_compaction():
    steps = [_step("2026-10-26T01:00:00.000Z"),
             _step("2026-10-26T02:00:00.000Z"),
             _step("2026-10-26T03:00:00.000Z")]
    plain = estimate_usage([_draft(0, steps)], "s", "m", "p", "src")
    cut = estimate_usage([_draft(0, steps)], "s", "m", "p", "src",
                         ["2026-10-26T01:30:00.000Z"])
    assert _reads(plain) == [0, 200, 400]
    assert _reads(cut) == [0, 0, 200]  # restarts before the 2nd step


def test_context_is_capped_at_the_window():
    big = _step("2026-10-26T01:00:00.000Z", chars=4 * WINDOW_TOKENS)
    usage = estimate_usage([_draft(0, [big, big, big])], "s", "m", "p",
                           "src")
    assert max(_reads(usage)) == WINDOW_TOKENS
