"""Data-quality, coverage-gap, and reconciliation reporting."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from tuner.reports import aggregate as agg
from tuner.reports import usage_query as uq
from tuner.reports.periods import Period

TOKENS = ("input_tokens + output_tokens + cache_write_tokens + "
          "cache_read_tokens")


def _marks(n: int) -> str:
    """SQL placeholders."""
    return ",".join("?" * n)


def reconciliation(conn: sqlite3.Connection, session_ids: list[str]
                   ) -> dict:
    """Compare session totals with task-attributed totals.

    Covers every task of the involved sessions (not only the period's) so
    the check is independent of where period boundaries fall. Whatever is
    not attributed (e.g. subagents that could not be linked to a turn)
    is reported as `unattributed`, never silently dropped.
    """
    if not session_ids:
        return {"session_total": 0, "attributed": 0, "unattributed": 0,
                "unlinked_subagent_sessions": 0, "reconciled": True}
    m = _marks(len(session_ids))
    total = conn.execute(
        f"SELECT COALESCE(SUM({TOKENS}),0) FROM {uq.USAGE} WHERE "
        f"session_id IN ({m}) OR session_id IN (SELECT id FROM sessions "
        f"WHERE parent_id IN ({m}))", session_ids * 2).fetchone()[0]
    task_ids = [r[0] for r in conn.execute(
        f"SELECT id FROM tasks WHERE session_id IN ({m})", session_ids)]
    rows = [r for rs in uq.load_task_usage(conn, task_ids).values()
            for r in rs]
    attributed = agg.totals(rows)["total"]
    unlinked = conn.execute(
        f"SELECT COUNT(*) FROM sessions c WHERE c.parent_id IN ({m}) AND "
        "NOT EXISTS (SELECT 1 FROM events e WHERE e.kind='subagent_spawn' "
        "AND e.session_id = c.parent_id AND e.turn_id IS NOT NULL AND "
        "json_extract(e.data_json,'$.agent_ref') = c.agent_ref)",
        session_ids).fetchone()[0]
    return {"session_total": total, "attributed": attributed,
            "unattributed": total - attributed,
            "unlinked_subagent_sessions": unlinked,
            "reconciled": total == attributed}


def _when(ts: str) -> datetime:
    """Parse a stored UTC timestamp."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _dashboard_gaps(conn: sqlite3.Connection, period: Period,
                    est_rows: list[dict]) -> list[dict]:
    """Ask for a dashboard CSV, and report requests that matched nothing."""
    gaps: list[dict] = []
    n = conn.execute("SELECT COUNT(*) FROM dashboard_requests").fetchone()[0]
    cursor_est = any(r.get("source") == "cursor_local_transcript"
                     for r in est_rows)
    if cursor_est and not n:
        gaps.append({
            "code": "cursor_dashboard_missing",
            "message": "Cursor totals are estimates. Import a dashboard "
                       "usage CSV to replace matched turns with measured "
                       "numbers: `tuner import cursor <file>`, or "
                       "`tuner import cursor --fetch` (sends the Cursor "
                       "session token to cursor.com)."})
    rows = conn.execute(
        "SELECT ts, input_tokens + output_tokens + cache_write_tokens + "
        "cache_read_tokens AS n FROM dashboard_requests "
        "WHERE turn_id IS NULL").fetchall()
    hit = [r for r in rows if period.start <= _when(r["ts"]) < period.end]
    if hit:
        tokens = sum(r["n"] for r in hit)
        gaps.append({
            "code": "dashboard_unmatched", "requests": len(hit),
            "tokens": tokens,
            "message": f"{len(hit)} dashboard requests ({tokens:,} tokens) "
                       "in this period did not match a local turn (start "
                       "within 3s), so they are not in task totals."})
    return gaps


def data_quality(conn: sqlite3.Connection, period: Period,
                 tasks: list[sqlite3.Row], usage: dict) -> dict:
    """Coverage gaps, collection errors and reconciliation summary."""
    sessions = sorted({t["session_id"] for t in tasks})
    gaps: list[dict] = []
    est_rows = [r for t in tasks for r in usage.get(t["id"], [])
                if r["measurement"] != "measured"]
    if est_rows:
        gaps.append({
            "code": "estimated_tokens",
            "message": "Some token counts are estimates (the agent does "
                       "not expose exact usage).",
            "tokens": agg.totals(est_rows)["total"]})
    gaps.extend(_dashboard_gaps(conn, period, est_rows))
    mtime = sum(1 for t in tasks if t["time_quality"] == "file_mtime")
    if mtime:
        gaps.append({
            "code": "timestamps_from_file_mtime",
            "message": "Task time is approximated by the transcript's "
                       "modification time (no per-message timestamps).",
            "tasks": mtime})
    no_model = sum(r["calls"] for t in tasks
                   for r in usage.get(t["id"], []) if not r["model"])
    if no_model:
        gaps.append({"code": "model_unknown", "calls": no_model,
                     "message": "Model unknown for some calls; cost "
                                "estimates are incomplete."})
    errs = conn.execute(
        "SELECT message, COUNT(*) n FROM collection_errors "
        "GROUP BY message ORDER BY n DESC LIMIT 20").fetchall()
    failed = conn.execute(
        "SELECT COUNT(*) FROM source_files WHERE status='error'"
    ).fetchone()[0]
    return {
        "coverage_gaps": gaps,
        "collection_errors": [{"message": e["message"], "files": e["n"]}
                              for e in errs],
        "failed_sources": failed,
        "reconciliation": reconciliation(conn, sessions),
    }
