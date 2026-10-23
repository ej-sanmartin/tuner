"""Deterministic grouping of turns into tasks.

Rules (all explicit and recorded as evidence on the task):
1. Every user prompt starts a new turn; turn boundaries are facts.
2. A turn becomes its own task by default (confidence "high").
3. If `merge_followups` is on, a short prompt (<= followup_max_chars) is
   merged into the previous task when the gap since the previous turn is
   within `idle_gap_minutes` (or unknown). Such tasks get confidence
   "medium" and list the merged turns, so nothing is hidden.
Task ids derive from the first turn id, so rescans never duplicate tasks.
Subagent sessions have no tasks of their own; their usage is attributed to
the parent turn that spawned them (see reports/usage_query.py).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TaskDraft:
    """A task before persistence."""

    session_id: str
    turn_ids: list[str] = field(default_factory=list)
    title: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    boundary: str = "new_prompt"
    merge_notes: list[dict] = field(default_factory=list)

    @property
    def id(self) -> str:
        """Stable id derived from the first turn."""
        digest = hashlib.sha1(self.turn_ids[0].encode()).hexdigest()
        return f"task:{digest[:16]}"

    @property
    def confidence(self) -> str:
        """High for explicit single-turn tasks, medium when merged."""
        return "high" if len(self.turn_ids) == 1 else "medium"


def _minutes_between(a: str | None, b: str | None) -> float | None:
    """Minutes from ISO time `a` to `b`; None if either is unknown."""
    if not a or not b:
        return None
    fa = datetime.fromisoformat(a.replace("Z", "+00:00"))
    fb = datetime.fromisoformat(b.replace("Z", "+00:00"))
    return (fb - fa).total_seconds() / 60


def group_turns(session_id: str, turns: list[sqlite3.Row],
                merge: bool, max_chars: int, idle_minutes: int
                ) -> list[TaskDraft]:
    """Group ordered turns into task drafts using the rules above."""
    tasks: list[TaskDraft] = []
    prev_end: str | None = None
    for turn in turns:
        gap = _minutes_between(prev_end, turn["started_at"])
        short = turn["prompt_chars"] <= max_chars
        can_merge = (merge and tasks and short
                     and (gap is None or gap <= idle_minutes))
        if can_merge:
            task = tasks[-1]
            task.turn_ids.append(turn["id"])
            task.merge_notes.append({
                "turn_id": turn["id"], "rule": "short_followup",
                "prompt_chars": turn["prompt_chars"], "gap_minutes": gap})
            task.boundary = "followup_merge"
        else:
            task = TaskDraft(
                session_id=session_id, turn_ids=[turn["id"]],
                title=turn["prompt_preview"][:120] or "(no prompt text)",
                started_at=turn["started_at"])
            tasks.append(task)
        task.ended_at = turn["ended_at"] or task.ended_at
        prev_end = turn["ended_at"] or prev_end
    return tasks


def rebuild_tasks(conn: sqlite3.Connection, session_ids: set[str],
                  merge: bool = True, max_chars: int = 80,
                  idle_minutes: int = 240) -> int:
    """Regroup tasks for the given main sessions; returns tasks written."""
    written = 0
    for sid in sorted(session_ids):
        sess = conn.execute(
            "SELECT id, kind, time_quality FROM sessions WHERE id=?",
            (sid,)).fetchone()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM task_turns WHERE task_id IN "
                         "(SELECT id FROM tasks WHERE session_id=?)", (sid,))
            conn.execute("DELETE FROM tasks WHERE session_id=?", (sid,))
            if sess is not None and sess["kind"] == "main":
                turns = conn.execute(
                    "SELECT id, started_at, ended_at, prompt_preview, "
                    "prompt_chars FROM turns WHERE session_id=? "
                    "ORDER BY seq", (sid,)).fetchall()
                drafts = group_turns(sid, turns, merge, max_chars,
                                     idle_minutes)
                for d in drafts:
                    _insert(conn, d, sess["time_quality"])
                written += len(drafts)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return written


def _insert(conn: sqlite3.Connection, d: TaskDraft, time_quality: str
            ) -> None:
    """Persist one task and its turn membership."""
    evidence = {"turn_ids": d.turn_ids, "merges": d.merge_notes}
    conn.execute(
        "INSERT INTO tasks(id, session_id, title, started_at, ended_at, "
        "time_quality, boundary, confidence, evidence_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (d.id, d.session_id, d.title, d.started_at, d.ended_at,
         time_quality, d.boundary, d.confidence, json.dumps(evidence)))
    conn.executemany("INSERT INTO task_turns(task_id, turn_id) VALUES (?,?)",
                     [(d.id, t) for t in d.turn_ids])
