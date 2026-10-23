"""Idempotent persistence of normalized records.

Each source file is replaced atomically: rows owned by the file are
deleted and re-inserted in one transaction, so re-importing the same file
never duplicates anything. Cross-file duplicates (e.g. resumed Claude Code
sessions replaying history) are resolved by primary key (first one wins).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime

from tuner.models import ParsedSource

OWNED_TABLES = ("sessions", "turns", "usage_events", "tool_calls", "events")


def now_iso() -> str:
    """Current UTC time as ISO-8601."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_unchanged(conn: sqlite3.Connection, path: str,
                 fingerprint: str) -> bool:
    """True when the file was already imported with this fingerprint."""
    row = conn.execute(
        "SELECT fingerprint, status FROM source_files WHERE path=?",
        (path,)).fetchone()
    return bool(row and row["fingerprint"] == fingerprint
                and row["status"] == "ok")


def _ins(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    """INSERT OR IGNORE rows (list of dicts with identical keys)."""
    if not rows:
        return
    cols = list(rows[0])
    sql = (f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) "
           f"VALUES ({','.join('?' * len(cols))})")
    conn.executemany(sql, [[r[c] for c in cols] for r in rows])


def replace_source(conn: sqlite3.Connection, path: str, agent: str,
                   fingerprint: str, parsed: ParsedSource) -> None:
    """Atomically replace all rows derived from one source file."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table in OWNED_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE source_path=?", (path,))
        _ins(conn, "sessions", [
            {**{k: v for k, v in asdict(s).items() if k != "meta"},
             "source_path": path,
             "meta_json": json.dumps(s.meta, sort_keys=True)}
            for s in parsed.sessions])
        _ins(conn, "turns", [{**asdict(t), "source_path": path}
                             for t in parsed.turns])
        _ins(conn, "usage_events", [{**asdict(u), "source_path": path}
                                    for u in parsed.usage])
        _ins(conn, "tool_calls", [
            {**asdict(t), "is_error": _tri(t.is_error), "source_path": path}
            for t in parsed.tools])
        _ins(conn, "events", [
            {**{k: v for k, v in asdict(e).items() if k != "data"},
             "data_json": json.dumps(e.data, sort_keys=True),
             "source_path": path} for e in parsed.events])
        conn.execute("DELETE FROM collection_errors WHERE source_path=?",
                     (path,))
        ts = now_iso()
        conn.executemany(
            "INSERT INTO collection_errors(source_path, message, ts) "
            "VALUES (?,?,?)", [(path, m, ts) for m in parsed.errors])
        status = "ok"
        conn.execute(
            "INSERT INTO source_files(path, agent, fingerprint, parsed_at, "
            "status, detail) VALUES (?,?,?,?,?,NULL) "
            "ON CONFLICT(path) DO UPDATE SET agent=excluded.agent, "
            "fingerprint=excluded.fingerprint, "
            "parsed_at=excluded.parsed_at, status=excluded.status, "
            "detail=NULL",
            (path, agent, fingerprint, ts, status))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _tri(value: bool | None) -> int | None:
    """Encode a nullable bool for SQLite."""
    return None if value is None else int(value)


def record_failure(conn: sqlite3.Connection, path: str, agent: str,
                   message: str) -> None:
    """Remember that a source could not be read, and why."""
    ts = now_iso()
    conn.execute(
        "INSERT INTO source_files(path, agent, fingerprint, parsed_at, "
        "status, detail) VALUES (?,?,'',?,'error',?) ON CONFLICT(path) "
        "DO UPDATE SET status='error', detail=excluded.detail, "
        "parsed_at=excluded.parsed_at", (path, agent, ts, message))
    conn.execute("DELETE FROM collection_errors WHERE source_path=? AND "
                 "message=?", (path, message))
    conn.execute("INSERT INTO collection_errors(source_path, message, ts) "
                 "VALUES (?,?,?)", (path, message, ts))


def kv_get(conn: sqlite3.Connection, key: str, default: str | None = None):
    """Read a small persisted state value."""
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Write a small persisted state value."""
    conn.execute("INSERT INTO kv(key, value) VALUES (?,?) ON CONFLICT(key) "
                 "DO UPDATE SET value=excluded.value", (key, value))
