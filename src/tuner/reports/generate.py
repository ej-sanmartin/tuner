"""Write a report folder: usage.json (+ analysis.json) and report.html."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tuner import paths
from tuner.config import Config
from tuner.fsutil import atomic_write_text, canonical_json, sha256_text
from tuner.reports.html import render_html
from tuner.reports.periods import Period
from tuner.reports.snapshot import build_snapshot
from tuner.storage.repo import now_iso


@dataclass
class ReportResult:
    """Paths and metadata of a generated report."""

    period_id: str
    directory: Path
    usage: dict
    usage_hash: str
    html_path: Path
    analysis_valid: bool


def report_dir(period_id: str) -> Path:
    """Folder for one period's artifacts."""
    return paths.reports_dir() / period_id


def content_hash(usage: dict) -> str:
    """Hash of snapshot content excluding volatile generation time."""
    stable = {k: v for k, v in usage.items() if k != "generated_at"}
    return sha256_text(canonical_json(stable))


def load_analysis(directory: Path, usage_hash: str) -> dict | None:
    """Load analysis.json only if it matches the current snapshot."""
    path = directory / "analysis.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if data.get("snapshot_hash") == usage_hash else None


def skill_history(conn: sqlite3.Connection, track: bool) -> list[dict]:
    """Skill change history (optionally with effectiveness)."""
    from tuner.skills.history import load_history
    return load_history(conn, track)


def render_report(conn: sqlite3.Connection, directory: Path, usage: dict,
                  usage_hash: str, track: bool = True
                  ) -> tuple[Path, bool]:
    """(Re)write report.html from usage.json + valid analysis.json."""
    analysis = load_analysis(directory, usage_hash)
    html = render_html(usage, analysis, skill_history(conn, track))
    out = directory / "report.html"
    atomic_write_text(out, html)
    return out, analysis is not None


def generate(conn: sqlite3.Connection, cfg: Config, period: Period,
             top_n: int | None = None, now: datetime | None = None
             ) -> ReportResult:
    """Build usage.json and report.html for `period` (idempotent)."""
    now = now or datetime.now(UTC)
    usage = build_snapshot(conn, cfg, period, top_n, now)
    digest = content_hash(usage)
    directory = report_dir(period.id)
    atomic_write_text(directory / "usage.json",
                      json.dumps(usage, indent=2, sort_keys=False) + "\n")
    html_path, valid = render_report(
        conn, directory, usage, digest, cfg.skills.track_effectiveness)
    conn.execute(
        "INSERT INTO report_periods(period_id, period_start, period_end, "
        "top_n, status, generated_at, usage_hash, report_dir) "
        "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(period_id) DO UPDATE SET "
        "top_n=excluded.top_n, status=excluded.status, "
        "generated_at=excluded.generated_at, usage_hash=excluded.usage_hash",
        (period.id, period.start_iso, period.end_iso,
         usage["selection"]["top_n"],
         "partial" if period.partial else "complete", now_iso(), digest,
         str(directory)))
    return ReportResult(period.id, directory, usage, digest, html_path,
                        valid)
