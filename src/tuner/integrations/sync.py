"""Bring already-installed integrations in line with this Tuner version.

Only things that are currently installed are refreshed, so an upgrade
never adds an integration the user opted out of (hooks, skill, schedule).
"""

from __future__ import annotations

import sqlite3

from tuner import __version__
from tuner.config import Config
from tuner.integrations import cursor_hooks, skill_install
from tuner.storage import repo


def mark_synced(conn: sqlite3.Connection) -> None:
    """Remember which Tuner version last refreshed the integrations."""
    repo.kv_set(conn, "synced_version", __version__)


def needs_sync(conn: sqlite3.Connection) -> str | None:
    """Last synced version if it differs from this one, else None."""
    last = repo.kv_get(conn, "synced_version", "")
    return None if last == __version__ else (last or "unknown")


def sync(cfg: Config) -> list[tuple[str, str]]:
    """Refresh installed pieces; returns [(name, result)] for display."""
    from tuner.commands.schedule import install_job
    from tuner.scheduler import get_scheduler
    from tuner.storage import connect
    conn = connect()  # applies pending database migrations
    done = [("database", "schema up to date")]
    if cursor_hooks.installed_events():
        cursor_hooks.install()
        done.append(("cursor hooks", "refreshed"))
    if skill_install.is_managed(skill_install.target_dir(
            cfg.skills.skill_dir)):
        skill_install.install(cfg.skills.skill_dir)
        done.append(("/tuner skill", "refreshed"))
    if get_scheduler().status().get("installed"):
        install_job(cfg)
        done.append(("schedule", "re-registered"))
    mark_synced(conn)
    conn.close()
    return done
