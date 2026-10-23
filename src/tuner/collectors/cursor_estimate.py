"""Documented token estimation for Cursor (which exposes no usage data).

Method `cursor_visible_v1` / `cursor_bubbles_v1`
------------------------------------------------
For each model call ("step") in conversation order:

* output_tokens      = ceil(chars produced / 4)   (text, tool arguments,
                       plus thinking when bubble data is available)
* input_tokens       = ceil(chars newly added to context / 4)  (the user
                       prompt, or the previous tool result when known)
* cache_read_tokens  = ceil(all earlier context chars / 4). Agent loops
                       resend the whole prefix each step; we assume it is
                       served from the provider's prompt cache.

Known gaps (always reported): system prompt and tool schemas, hidden
reasoning when bubbles are unavailable, tool results when bubbles are
unavailable, tokenizer differences, context compaction, and the cache
assumption. Treat results as a *relative effort proxy*, never as billing.
"""

from __future__ import annotations

from tuner.collectors.common import estimate_tokens
from tuner.collectors.cursor_parser import TurnDraft
from tuner.models import ESTIMATED, MEASURED, UsageRec

KNOWN_GAPS = {
    "cursor_visible_v1": [
        "system_prompt_and_tool_schemas", "hidden_reasoning",
        "tool_results", "tokenizer_difference", "cache_assumption"],
    "cursor_bubbles_v1": [
        "system_prompt_and_tool_schemas", "tokenizer_difference",
        "cache_assumption"],
}


def estimate_usage(drafts: list[TurnDraft], session_id: str,
                   default_model: str | None, source_path: str,
                   source: str) -> list[UsageRec]:
    """Turn step sizes into usage records (measured if source has them)."""
    out: list[UsageRec] = []
    context_chars = 0
    for draft in drafts:
        method = draft.method
        confidence = "medium" if method == "cursor_bubbles_v1" else "low"
        for i, step in enumerate(draft.steps):
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
                    cache_read_tokens=estimate_tokens(context_chars),
                    measurement=ESTIMATED, confidence=confidence,
                    source=source, method=method))
            context_chars += step.in_chars + step.out_chars
    return out
