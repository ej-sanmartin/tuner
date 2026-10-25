"""Incremental, idempotent collection pipeline.

Unchanged files (same size/mtime/salt) are skipped; changed files are
re-parsed in full and replace their previous rows atomically. A file lock
prevents concurrent scheduled and manual runs from racing.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime

from tuner import paths
from tuner.attribution import ATTRIBUTION_VERSION, rebuild_tasks
from tuner.collectors import UsageCollector
from tuner.config import Config
from tuner.storage import repo
from tuner.storage.locking import FileLock, LockBusy


@dataclass
class CollectStats:
    """Outcome of one collection run."""

    seen: int = 0
    parsed: int = 0
    skipped: int = 0
    failed: int = 0
    tasks_written: int = 0
    seconds: float = 0.0
    agents: dict[str, dict] = field(default_factory=dict)
    busy: bool = False
    messages: list[str] = field(default_factory=list)


def _collect_one(conn: sqlite3.Connection, col: UsageCollector,
                 since: datetime | None, full: bool, stats: CollectStats,
                 touched: set[str]) -> None:
    """Import all changed sources of one collector."""
    info = stats.agents.setdefault(
        col.name, {"seen": 0, "parsed": 0, "skipped": 0, "failed": 0})
    for src in col.iter_sources(since):
        stats.seen += 1
        info["seen"] += 1
        path = str(src.path)
        if not full and repo.is_unchanged(conn, path, src.fingerprint):
            stats.skipped += 1
            info["skipped"] += 1
            continue
        try:
            parsed = col.parse(src)
            repo.replace_source(conn, path, col.name, src.fingerprint,
                                parsed)
        except Exception as exc:  # one bad file must not stop the run
            repo.record_failure(conn, path, col.name,
                                f"{type(exc).__name__}: {exc}")
            stats.failed += 1
            info["failed"] += 1
            continue
        stats.parsed += 1
        info["parsed"] += 1
        for s in parsed.sessions:
            touched.add(s.id)
            if s.parent_id:
                touched.add(s.parent_id)


def _main_sessions(conn: sqlite3.Connection) -> set[str]:
    """Ids of all main (non-subagent) sessions."""
    return {r[0] for r in conn.execute(
        "SELECT id FROM sessions WHERE kind='main'")}


def collect(conn: sqlite3.Connection, collectors: list[UsageCollector],
            cfg: Config, since: datetime | None = None, full: bool = False,
            lock_timeout: float = 0.0) -> CollectStats:
    """Run all collectors incrementally and refresh task attribution."""
    stats = CollectStats()
    started = time.monotonic()
    try:
        with FileLock(paths.data_dir() / "collect.lock", lock_timeout):
            touched: set[str] = set()
            for col in collectors:
                _collect_one(conn, col, since, full, stats, touched)
            a = cfg.attribution
            rules = (f"{ATTRIBUTION_VERSION}:{a.link_followups}:"
                     f"{a.followup_max_chars}:{a.idle_gap_minutes}")
            stale = repo.kv_get(conn, "attribution_rules") != rules
            if touched or full or stale:
                if full or stale:  # grouping rules changed: regroup all
                    touched = _main_sessions(conn) | touched
                stats.tasks_written = rebuild_tasks(
                    conn, touched, a.link_followups, a.followup_max_chars,
                    a.idle_gap_minutes)
                repo.kv_set(conn, "attribution_rules", rules)
            repo.kv_set(conn, "last_collect", repo.now_iso())
    except LockBusy:
        stats.busy = True
        stats.messages.append("another collection is running; skipped")
    finally:
        for col in collectors:
            close = getattr(col, "close", None)
            if close:
                close()
    stats.seconds = round(time.monotonic() - started, 2)
    return stats
