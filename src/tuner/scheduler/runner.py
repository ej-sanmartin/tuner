"""Idempotent scheduled run: collect, find due periods, generate, notify.

Safe to invoke any number of times (timer, login, manual): periods already
recorded as complete are never regenerated, and a lock prevents two runs
from racing. Missed periods are generated up to the backfill limit.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from tuner import paths
from tuner.collect import collect
from tuner.collectors import build_collectors
from tuner.config import Config
from tuner.notifications import notify
from tuner.reports import generate as gen
from tuner.reports import periods
from tuner.reports.opener import open_file
from tuner.storage.locking import FileLock, LockBusy


def completed_ids(conn: sqlite3.Connection) -> set[str]:
    """Period ids with a finished (non-partial) report."""
    return {r[0] for r in conn.execute(
        "SELECT period_id FROM report_periods WHERE status='complete'")}


def due(conn: sqlite3.Connection, cfg: Config, now: datetime
        ) -> list[periods.Period]:
    """Periods that should be generated now (oldest first)."""
    r = cfg.report
    return periods.due_periods(now, r.period, r.day, r.time, r.timezone,
                               completed_ids(conn), r.catch_up,
                               r.backfill_limit)


def run_due(conn: sqlite3.Connection, cfg: Config,
            now: datetime | None = None, dry_run: bool = False,
            do_collect: bool = True,
            notifier: Callable[[str, str], bool] = notify,
            opener: Callable = open_file) -> list[gen.ReportResult]:
    """Generate every due report; returns the results (possibly empty)."""
    now = now or datetime.now(UTC)
    if dry_run:
        return [gen.ReportResult(p.id, gen.report_dir(p.id), {}, "",
                                 gen.report_dir(p.id) / "report.html",
                                 False) for p in due(conn, cfg, now)]
    try:
        lock = FileLock(paths.data_dir() / "schedule.lock", timeout=0)
        with lock:
            if do_collect:
                collect(conn, build_collectors(cfg), cfg, lock_timeout=60)
            results = []
            for period in due(conn, cfg, now):
                res = gen.generate(conn, cfg, period, now=now)
                results.append(res)
                _deliver(cfg, res, notifier, opener)
            return results
    except LockBusy:
        return []


def _deliver(cfg: Config, res: gen.ReportResult, notifier, opener) -> None:
    """Notify (and optionally open) a finished report."""
    ov = res.usage["overview"]
    if not ov["counts"]["tasks"]:
        return
    if cfg.delivery.notification:
        msg = (f"{ov['tokens']['total']:,} tokens across "
               f"{ov['counts']['tasks']} tasks. `tuner open`, then /tuner "
               "in your agent to analyze.")
        notifier(f"Tuner report ready ({res.period_id})", msg)
    if cfg.delivery.open_automatically:
        opener(res.html_path, cfg.delivery.opener)
