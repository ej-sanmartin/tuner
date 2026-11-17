"""Read-only SQLite helpers for local agent databases."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from tuner.collectors.base import SourceFile
from tuner.models import MEASURED, UsageRec


def connect_ro(path: Path) -> sqlite3.Connection:
    """Open `path` read-only. Raises sqlite3.Error if it cannot be read."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    """True when `name` is a table in this database."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone()
    return row is not None


def rows(conn: sqlite3.Connection, out_errors: list[str], sql: str
         ) -> list[sqlite3.Row]:
    """Run `sql`. On failure, record it and return no rows."""
    try:
        return list(conn.execute(sql))
    except sqlite3.Error as exc:
        out_errors.append(str(exc))
        return []


def as_int(value: object) -> int:
    """Integer from a SQLite or JSON number; 0 when it is missing."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_json(raw: object) -> object:
    """Decode a JSON string. Other values are returned unchanged."""
    if not isinstance(raw, str) or not raw:
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return None


def existing(cands: list[Path]) -> list[Path]:
    """Unique files among `cands`, in order."""
    seen: set[str] = set()
    out: list[Path] = []
    for cand in cands:
        try:
            key = os.path.normcase(str(cand.resolve()))
            ok = cand.is_file()
        except OSError:
            continue
        if ok and key not in seen:
            seen.add(key)
            out.append(cand)
    return out


def _mtime(path: Path) -> float | None:
    """mtime, or None when the file is absent."""
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def wal_salt(path: Path) -> str:
    """Size and mtime of the WAL, so uncheckpointed writes are visible."""
    wal = Path(f"{path}-wal")
    try:
        st = wal.stat()
    except OSError:
        return "0:0"
    return f"{st.st_size}:{st.st_mtime_ns}"


def fresh(path: Path, since: datetime | None) -> bool:
    """True when `path` or its WAL changed at or after `since`."""
    if since is None:
        return True
    cutoff = since.timestamp()
    times = [t for t in (_mtime(path), _mtime(Path(f"{path}-wal"))) if t]
    return any(t >= cutoff for t in times)


def db_source(path: Path, agent: str, since: datetime | None
              ) -> SourceFile | None:
    """One database as a source file, or None when it is unchanged / gone."""
    if not fresh(path, since):
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    return SourceFile(path, agent, st.st_size, st.st_mtime_ns, wal_salt(path))


def usage_rec(agent: str, uid: str, session_id: str, turn_id: str | None,
              ts: str | None, model: str | None, tokens: dict, source: str,
              method: str | None, path: Path, line: int) -> UsageRec:
    """One measured usage row. Reasoning tokens are counted as output."""
    reasoning = as_int(tokens.get("reasoning"))
    notes = [method] if method else []
    if reasoning:
        notes.append("reasoning_included_in_output")
    return UsageRec(
        id=f"{agent}:usage:{uid}", session_id=session_id, turn_id=turn_id,
        ts=ts, model=model or None,
        input_tokens=as_int(tokens.get("input")),
        output_tokens=as_int(tokens.get("output")) + reasoning,
        cache_write_tokens=as_int(tokens.get("cache_write")),
        cache_read_tokens=as_int(tokens.get("cache_read")),
        measurement=MEASURED, confidence="high", source=source,
        method="; ".join(notes) or None, source_path=str(path),
        source_line=line)
