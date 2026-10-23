"""Persist analyses and answer cache lookups."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tuner import paths
from tuner.fsutil import atomic_write_text
from tuner.reports.generate import report_dir
from tuner.storage.repo import now_iso


def history_dir() -> Path:
    """Immutable per-key copies of every saved analysis."""
    return paths.ensure_private_dir(paths.data_dir() / "analyses")


def current_file(period_id: str) -> Path:
    """The analysis embedded in the period's report."""
    return report_dir(period_id) / "analysis.json"


def save(conn: sqlite3.Connection, analysis: dict, selection: list[str]
         ) -> Path:
    """Write the analysis (history + report copy) and index it."""
    text = json.dumps(analysis, indent=2) + "\n"
    key, period = analysis["cache_key"], analysis["period"]
    atomic_write_text(history_dir() / f"{key}.json", text)
    atomic_write_text(current_file(period), text)
    conn.execute("UPDATE analyses SET status='superseded' WHERE "
                 "period_id=? AND status='valid'", (period,))
    conn.execute(
        "INSERT OR REPLACE INTO analyses(cache_key, period_id, "
        "snapshot_hash, task_ids_json, created_at, path, status) "
        "VALUES (?,?,?,?,?,?,'valid')",
        (key, period, analysis["snapshot_hash"], json.dumps(selection),
         now_iso(), str(history_dir() / f"{key}.json")))
    conn.commit()
    return current_file(period)


def lookup(conn: sqlite3.Connection, period_id: str, key: str
           ) -> dict | None:
    """The cached analysis for exactly this key, if still valid."""
    row = conn.execute("SELECT path FROM analyses WHERE cache_key=? AND "
                       "period_id=? AND status='valid'",
                       (key, period_id)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(Path(row["path"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def status(conn: sqlite3.Connection, period_id: str, key: str) -> str:
    """'valid' (cache hit), 'stale' (older analysis exists), or 'missing'."""
    if lookup(conn, period_id, key):
        return "valid"
    row = conn.execute("SELECT 1 FROM analyses WHERE period_id=?",
                       (period_id,)).fetchone()
    return "stale" if row else "missing"


def invalidate(conn: sqlite3.Connection, period_id: str | None = None
               ) -> int:
    """Mark analyses invalid and remove the report-embedded copy."""
    rows = conn.execute(
        "SELECT DISTINCT period_id FROM analyses WHERE status='valid'"
        + (" AND period_id=?" if period_id else ""),
        (period_id,) if period_id else ()).fetchall()
    for r in rows:
        current_file(r["period_id"]).unlink(missing_ok=True)
    cur = conn.execute(
        "UPDATE analyses SET status='invalidated' WHERE status='valid'"
        + (" AND period_id=?" if period_id else ""),
        (period_id,) if period_id else ())
    conn.commit()
    return cur.rowcount
