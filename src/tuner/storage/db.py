"""SQLite connection management and migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tuner import paths
from tuner.storage.schema import MIGRATIONS


def migrate(conn: sqlite3.Connection) -> None:
    """Apply any pending migrations in order."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, script in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version={version};"
                           "\nCOMMIT;")


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the Tuner database, migrated and ready."""
    path = path or paths.db_file()
    if str(path) != ":memory:":
        paths.ensure_private_dir(path.parent)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    migrate(conn)
    return conn
