"""Observational effectiveness of applied skill changes.

This is correlation, not causation: tasks before and after are different
work. We report sample sizes, whether the skill was observed in use, and
a deliberately cautious verdict.
"""

from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, timedelta

WINDOW_DAYS = 30
MIN_SAMPLE = 3
IMPROVE = 0.25  # median token drop needed to call it a possible win


def _task_tokens(conn: sqlite3.Connection, repo: str | None, start: str,
                 end: str) -> list[int]:
    """Total tokens per task in [start, end), optionally for one repo."""
    sql = (
        "SELECT SUM(u.input_tokens + u.output_tokens + u.cache_write_tokens"
        " + u.cache_read_tokens) AS total FROM tasks t JOIN sessions s ON "
        "s.id = t.session_id JOIN task_turns tt ON tt.task_id = t.id JOIN "
        "usage_effective u ON u.turn_id = tt.turn_id WHERE "
        "COALESCE(t.ended_at, t.started_at) >= ? AND "
        "COALESCE(t.ended_at, t.started_at) < ?")
    args: list = [start, end]
    if repo:
        sql += " AND s.repo = ?"
        args.append(repo)
    sql += " GROUP BY t.id"
    return [int(r["total"] or 0) for r in conn.execute(sql, args)]


def _uses_after(conn: sqlite3.Connection, name: str, applied: str) -> int:
    """Tool calls after `applied` that reference the skill."""
    row = conn.execute(
        "SELECT COUNT(*) n FROM tool_calls WHERE ts >= ? AND "
        "(target LIKE ? OR (name = 'Skill' AND target = ?))",
        (applied, f"%/{name}/SKILL.md%", name)).fetchone()
    return int(row["n"])


def iso(d: datetime) -> str:
    """UTC timestamp string used by the database."""
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def evaluate(conn: sqlite3.Connection, change: dict) -> dict:
    """Verdict for one applied change (dict with the skill_changes columns)."""
    applied = change.get("applied_at")
    if change["status"] != "applied" or not applied:
        return {"verdict": "not_applicable", "note": "not applied"}
    t0 = datetime.fromisoformat(applied.replace("Z", "+00:00"))
    repo = change.get("repo")
    before = _task_tokens(conn, repo, iso(t0 - timedelta(days=WINDOW_DAYS)),
                          iso(t0))
    after = _task_tokens(conn, repo, iso(t0), iso(t0 + timedelta(
        days=WINDOW_DAYS)))
    uses = _uses_after(conn, change["skill_name"], iso(t0))
    out = {"n_before": len(before), "n_after": len(after), "uses": uses,
           "window_days": WINDOW_DAYS}
    if min(len(before), len(after)) < MIN_SAMPLE:
        return {**out, "verdict": "insufficient_data",
                "note": f"need >= {MIN_SAMPLE} tasks before and after"}
    if uses == 0:
        return {**out, "verdict": "not_observed_in_use",
                "note": "skill was never seen being used after applying"}
    mb, ma = statistics.median(before), statistics.median(after)
    change_pct = (ma - mb) / mb if mb else 0.0
    out["median_tokens_change"] = round(change_pct, 3)
    if change_pct <= -IMPROVE:
        verdict = "possible_improvement"
    elif change_pct >= IMPROVE:
        verdict = "possible_regression"
    else:
        verdict = "no_clear_change"
    return {**out, "verdict": verdict,
            "note": f"median tokens/task {change_pct:+.0%} (correlation "
                    "only; tasks differ)"}
