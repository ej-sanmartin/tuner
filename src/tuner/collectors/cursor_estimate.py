"""Documented token estimation for Cursor (which exposes no usage data).

Method `cursor_visible_v2` / `cursor_bubbles_v2`
------------------------------------------------
For each model call ("step") in conversation order:

* output_tokens      = ceil(chars produced / 4)   (text, tool arguments,
                       plus thinking when bubble data is available)
* input_tokens       = ceil(chars newly added to context / 4)  (the user
                       prompt, or the previous tool result when known)
* cache_read_tokens  = ceil(earlier context chars / 4), capped at the
                       context window. Agent loops resend the whole prefix
                       each step; we assume it is served from the
                       provider's prompt cache.
* v2 (calibrated on a dashboard comparison): the context restarts at each
  compaction (hook `preCompact`), and is capped at WINDOW_TOKENS, which
  Cursor reports as `context_window_size` (300000); real contexts at
  auto-compaction were 280K-351K tokens. v1 let context grow unbounded and
  overstated one task by 4.6x; with the reset it was within 1%.

Known gaps (always reported): system prompt and tool schemas, hidden
reasoning when bubbles are unavailable, tool results when bubbles are
unavailable, tokenizer differences, context compaction, and the cache
assumption. Treat results as a *relative effort proxy*, never as billing.
"""

from __future__ import annotations

from tuner.collectors.common import estimate_tokens
from tuner.collectors.cursor_parser import TurnDraft
from tuner.models import ESTIMATED, MEASURED, UsageRec

WINDOW_TOKENS = 300_000

KNOWN_GAPS = {
    "cursor_visible_v2": [
        "system_prompt_and_tool_schemas", "hidden_reasoning",
        "tool_results", "tokenizer_difference", "cache_assumption",
        "oversized_tool_results"],
    "cursor_bubbles_v2": [
        "system_prompt_and_tool_schemas", "tokenizer_difference",
        "cache_assumption", "oversized_tool_results"],
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
    context_chars = 0
    for draft in drafts:
        method = draft.method
        confidence = "medium" if method == "cursor_bubbles_v2" else "low"
        for i, step in enumerate(draft.steps):
            when = step.ts or draft.rec.started_at
            while pending and when and when > pending[0]:
                pending.pop(0)
                context_chars = 0  # compaction replaced the context
            base = dict(
                id=f"{session_id}:usage:{draft.rec.seq}:{i}",
                session_id=session_id, turn_id=draft.rec.id,
                ts=step.ts or draft.rec.started_at,
                model=step.model or default_model,
                source_path=source_path, source_line=draft.rec.source_line)
            if step.tokens_in or step.tokens_out:
                out.append(UsageRec(
                    **base, input_tokens=step.tokens_in,
                    output_tokens=step.tokens_out, measurement=MEASURED,
                    confidence="medium", source="cursor_state_db"))
            else:
                out.append(UsageRec(
                    **base, input_tokens=estimate_tokens(step.in_chars),
                    output_tokens=estimate_tokens(step.out_chars),
                    cache_read_tokens=min(estimate_tokens(context_chars),
                                          WINDOW_TOKENS),
                    measurement=ESTIMATED, confidence=confidence,
                    source=source, method=method))
            context_chars += step.in_chars + step.out_chars
    return out
