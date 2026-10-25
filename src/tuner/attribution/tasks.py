"""Deterministic grouping of turns into tasks.

A task is one user prompt (the start of a workflow) plus everything the
agent did for it, including subagents. Rules (recorded as task evidence):
1. Every user prompt is its own task (boundary "new_prompt", high
   confidence). Nothing is ever merged, so per-prompt cost stays visible.
2. A prompt may be *linked* to the previous task as a continuation when
   the gap since that turn is within `idle_gap_minutes` (or unknown) and
   either the previous turn was interrupted/errored or the prompt is
   short (<= followup_max_chars). The link carries rule and gap, and
   tasks in a chain share a `thread_id` (the first task's id).
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

ATTRIBUTION_VERSION = "2"  # bump to regroup existing data on next collect
INTERRUPTED = ("interrupted", "error")


@dataclass
class TaskDraft:
    """A task before persistence."""

    session_id: str
    turn_ids: list[str] = field(default_factory=list)
    title: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    continues: dict | None = None
    thread_id: str = ""

    @property
    def id(self) -> str:
        """Stable id derived from the first turn."""
        digest = hashlib.sha1(self.turn_ids[0].encode()).hexdigest()
        return f"task:{digest[:16]}"


def _minutes_between(a: str | None, b: str | None) -> float | None:
    """Minutes from ISO time `a` to `b`; None if either is unknown."""
    if not a or not b:
        return None
    fa = datetime.fromisoformat(a.replace("Z", "+00:00"))
    fb = datetime.fromisoformat(b.replace("Z", "+00:00"))
    return (fb - fa).total_seconds() / 60


def _continuation(prev: sqlite3.Row, turn: sqlite3.Row,
                  gap: float | None, link: bool, max_chars: int,
                  idle_minutes: int) -> tuple[str, float | None] | None:
    """(rule, gap) if `turn` plausibly continues the previous task."""
    if not link or (gap is not None and gap > idle_minutes):
        return None
    if prev["outcome"] in INTERRUPTED:
        return "interrupted_previous", gap
    if turn["prompt_chars"] <= max_chars:
        return "short_followup", gap
    return None


def group_turns(session_id: str, turns: list[sqlite3.Row],
                link: bool, max_chars: int, idle_minutes: int
                ) -> list[TaskDraft]:
    """One task per turn; continuation links per the rules above."""
    tasks: list[TaskDraft] = []
    prev_turn: sqlite3.Row | None = None
    prev_end: str | None = None
    for turn in turns:
        task = TaskDraft(
            session_id=session_id, turn_ids=[turn["id"]],
            title=turn["prompt_preview"][:120] or "(no prompt text)",
            started_at=turn["started_at"], ended_at=turn["ended_at"])
        task.thread_id = task.id
        if tasks and prev_turn is not None:
            gap = _minutes_between(prev_end, turn["started_at"])
            hit = _continuation(prev_turn, turn, gap, link, max_chars,
                                idle_minutes)
            if hit:
                task.continues = {"task_id": tasks[-1].id, "rule": hit[0],
                                  "gap_minutes": hit[1]}
                task.thread_id = tasks[-1].thread_id
        tasks.append(task)
        prev_turn = turn
        prev_end = turn["ended_at"] or prev_end
    return tasks


def rebuild_tasks(conn: sqlite3.Connection, session_ids: set[str],
                  link: bool = True, max_chars: int = 80,
                  idle_minutes: int = 30) -> int:
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
                    "prompt_chars, outcome FROM turns WHERE session_id=? "
                    "ORDER BY seq", (sid,)).fetchall()
                drafts = group_turns(sid, turns, link, max_chars,
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
    evidence = {"turn_ids": d.turn_ids, "continues": d.continues,
                "thread_id": d.thread_id}
    conn.execute(
        "INSERT INTO tasks(id, session_id, title, started_at, ended_at, "
        "time_quality, boundary, confidence, evidence_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (d.id, d.session_id, d.title, d.started_at, d.ended_at,
         time_quality, "new_prompt", "high", json.dumps(evidence)))
    conn.executemany("INSERT INTO task_turns(task_id, turn_id) VALUES (?,?)",
                     [(d.id, t) for t in d.turn_ids])
