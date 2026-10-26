"""Documented token estimation for Cursor (which exposes no usage data).

Method `cursor_visible_v1` / `cursor_bubbles_v1`
------------------------------------------------
Parameters were fitted to 136 requests from the Cursor dashboard usage CSV
(one row per request; see docs/PROGRESS.md). Per model call ("step"):

* context   = SYSTEM_TOKENS + everything added earlier in the
              conversation, capped at WINDOW_TOKENS. Tool results are
              capped at RESULT_CAP_TOKENS each: Cursor does not resend
              them in full, so counting them in full overshot 4-6x.
              The context restarts at each compaction (hook `preCompact`).
* input_tokens      = the first step of a request writes the whole
                      context; later steps write only the new tool result
                      and the previous output (Cursor's two input columns
                      are summed here).
* cache_read_tokens = the rest of the context, re-read every step.
* output_tokens     = chars/4 * OUTPUT_FACTOR (hidden reasoning and
                      tokenizer differences; measured median 1.7x).

Known gaps (always reported): hidden reasoning when bubbles are
unavailable, per-model system prompt size, tokenizer differences, and the
new-input / cache-read split (Cursor's cache behaviour is not modelled; the
split is right on average but noisy). Totals are typically within ~60% of
the dashboard. Treat results as a *relative effort proxy*, never billing.
"""

from __future__ import annotations

import math

from tuner.collectors.common import estimate_tokens
from tuner.collectors.cursor_parser import TurnDraft
from tuner.models import ESTIMATED, MEASURED, UsageRec

WINDOW_TOKENS = 300_000    # Cursor `context_window_size` (preCompact hook)
SYSTEM_TOKENS = 15_000     # system prompt, tool schemas, rules (fitted)
RESULT_CAP_TOKENS = 2_000  # per tool result kept in context (fitted)
OUTPUT_FACTOR = 1.7        # real output / visible chars (fitted)

KNOWN_GAPS = {
    "cursor_visible_v1": [
        "hidden_reasoning", "tool_results", "tokenizer_difference",
        "input_cache_split", "system_prompt_size"],
    "cursor_bubbles_v1": [
        "tokenizer_difference", "input_cache_split", "system_prompt_size"],
}


def estimate_usage(drafts: list[TurnDraft], session_id: str,
                   default_model: str | None, source_path: str,
                   source: str, compactions: list[str] | None = None
                   ) -> list[UsageRec]:
    """Turn step sizes into usage records (measured if source has them).

    `compactions` are ISO times of context compactions; the estimated
    context restarts at the first step after each.
    """
    out: list[UsageRec] = []
    pending = sorted(compactions or [])
    context = 0  # tokens added to the conversation so far
    for draft in drafts:
        method = draft.method
        confidence = "medium" if method == "cursor_bubbles_v1" else "low"
        prev_out = 0
        for i, step in enumerate(draft.steps):
            when = step.ts or draft.rec.started_at
            while pending and when and when > pending[0]:
                pending.pop(0)
                context = 0  # compaction replaced the context
            base = dict(
                id=f"{session_id}:usage:{draft.rec.seq}:{i}",
                session_id=session_id, turn_id=draft.rec.id,
                ts=step.ts or draft.rec.started_at,
                model=step.model or default_model,
                source_path=source_path, source_line=draft.rec.source_line)
            added = estimate_tokens(step.in_chars)
            if i:
                added = min(added, RESULT_CAP_TOKENS)
            produced = estimate_tokens(step.out_chars)
            if step.tokens_in or step.tokens_out:
                out.append(UsageRec(
                    **base, input_tokens=step.tokens_in,
                    output_tokens=step.tokens_out, measurement=MEASURED,
                    confidence="medium", source="cursor_state_db"))
            else:
                window = min(SYSTEM_TOKENS + context, WINDOW_TOKENS)
                new = window if i == 0 else min(added + prev_out, window)
                out.append(UsageRec(
                    **base, input_tokens=new, cache_read_tokens=window - new,
                    output_tokens=math.ceil(produced * OUTPUT_FACTOR),
                    measurement=ESTIMATED, confidence=confidence,
                    source=source, method=method))
            context += added + produced
            prev_out = produced
    return out
