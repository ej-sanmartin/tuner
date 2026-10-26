"""Merge optional state-DB bubbles and hook events into transcript drafts.

Alignment is by user-turn order. If counts disagree we do NOT guess; the
caller records a coverage gap and keeps transcript-only estimates.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher

from tuner.collectors.common import iso_utc
from tuner.collectors.cursor_parser import Step, TurnDraft
from tuner.collectors.cursor_state import Bubble, Composer

_ERROR_STATUSES = {"error", "failed", "rejected", "cancelled", "canceled"}
_TIER = re.compile(r"(-(low|medium|high|xhigh|max|fast))+$")
PROMPT_MATCH_S = 5.0  # hook fires within seconds of the turn start


def _split(bubbles: list[Bubble]) -> list[tuple[Bubble, list[Bubble]]]:
    """Group bubbles into (user bubble, following assistant bubbles)."""
    groups: list[tuple[Bubble, list[Bubble]]] = []
    for b in bubbles:
        if b.kind == 1:
            groups.append((b, []))
        elif groups:
            groups[-1][1].append(b)
    return groups


def _steps(user_chars: int, assistants: list[Bubble]) -> list[Step]:
    """One step per model call: a run of bubbles ending in a tool call."""
    steps: list[Step] = []
    pending_in, cur = user_chars, Step()
    cur.in_chars = pending_in
    for b in assistants:
        cur.out_chars += b.text_chars + b.thinking_chars + b.args_chars
        cur.ts = cur.ts or b.ts
        cur.model = cur.model or b.model
        cur.tokens_in += b.tokens_in
        cur.tokens_out += b.tokens_out
        if b.tool_call_id:
            steps.append(cur)
            cur = Step(in_chars=b.result_chars)
    if cur.out_chars:
        steps.append(cur)
    return steps


def apply_bubbles(drafts: list[TurnDraft], comp: Composer) -> str | None:
    """Enrich drafts in place using prompt-prefix sequence alignment.

    The transcript can contain extra synthetic user messages (e.g. after
    compaction) and may lag the DB; unmatched turns keep transcript-only
    estimates. Returns a coverage note when some turns are unaligned.
    """
    groups = _split(comp.bubbles)
    matcher = SequenceMatcher(
        None, [d.head for d in drafts], [g[0].text_head for g in groups],
        autojunk=False)
    matched = 0
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            _enrich_turn(drafts[a + k], *groups[b + k])
            matched += 1
    if matched == len(drafts):
        return None
    return ("some transcript turns could not be aligned with the state DB; "
            "those use transcript-only estimates")


def _enrich_turn(draft: TurnDraft, ub: Bubble, rest: list[Bubble]) -> None:
    """Apply one user bubble group to its matching draft."""
    assistants = [b for b in rest if b.kind == 2]
    draft.rec.started_at = ub.ts
    draft.rec.ended_at = next((b.ts for b in reversed(rest) if b.ts), ub.ts)
    if assistants:
        draft.steps = _steps(draft.rec.prompt_chars, assistants)
        draft.method = "cursor_bubbles_v1"
    calls = [b for b in assistants if b.tool_call_id]
    if len(calls) == len(draft.tools):
        for tool, b in zip(draft.tools, calls, strict=True):
            tool.ts = b.ts
            if b.tool_status:
                tool.is_error = b.tool_status.lower() in _ERROR_STATUSES


def dominant_model(drafts: list[TurnDraft], fallback: str | None
                   ) -> str | None:
    """Most frequent step model, else the fallback."""
    c = Counter(s.model for d in drafts for s in d.steps if s.model)
    return c.most_common(1)[0][0] if c else fallback


def apply_hooks(drafts: list[TurnDraft], events: list[dict]) -> bool:
    """Fill missing turn times from beforeSubmitPrompt/stop hook events.

    Matches k-th prompt event to k-th turn only when counts agree.
    Returns True if any timestamps were applied.
    """
    starts = [e for e in events if e["event"] == "beforeSubmitPrompt"]
    if len(starts) != len(drafts):
        return False
    stops = [e for e in events if e["event"] == "stop"]
    for i, (draft, ev) in enumerate(zip(drafts, starts, strict=True)):
        draft.rec.started_at = draft.rec.started_at or iso_utc(ev["ts"])
        nxt = starts[i + 1]["ts"] if i + 1 < len(starts) else float("inf")
        ended = [s["ts"] for s in stops if ev["ts"] <= s["ts"] < nxt]
        if ended and not draft.rec.ended_at:
            draft.rec.ended_at = iso_utc(max(ended))
    return True


def apply_hook_models(drafts: list[TurnDraft], events: list[dict]) -> int:
    """Label each turn's steps with the model its prompt hook reported.

    A conversation can switch models between prompts, but the state DB
    keeps only the current one. The hook model equals the dashboard's.
    Matches by start time (nearest prompt within PROMPT_MATCH_S); returns
    the number of turns labelled.
    """
    prompts = [(e["ts"], _TIER.sub("", e["model"])) for e in events
               if e["event"] == "beforeSubmitPrompt" and e.get("model")]
    done = 0
    for draft in drafts:
        if not (draft.rec.started_at and prompts and draft.steps):
            continue
        start = datetime.fromisoformat(draft.rec.started_at).timestamp()
        ts, model = min(prompts, key=lambda p: abs(p[0] - start))
        if abs(ts - start) > PROMPT_MATCH_S:
            continue
        for step in draft.steps:
            step.model = model
        done += 1
    return done
