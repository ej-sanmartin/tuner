"""Skill change history (with effectiveness) for reports and the CLI."""

from __future__ import annotations

import sqlite3

from tuner.skills.evaluate import evaluate

COLUMNS = ("id, created_at, action, skill_name, scope, path, status, mode, "
           "applied_at, rolled_back_at, repo")


def pending_proposals(conn: sqlite3.Connection) -> list[dict]:
    """Applyable skill proposals (id, name, and the apply command)."""
    rows = conn.execute(
        "SELECT id, skill_name FROM skill_changes "
        "WHERE status IN ('proposed', 'approved') "
        "ORDER BY created_at").fetchall()
    return [{"id": r["id"], "skill_name": r["skill_name"],
             "apply": f"tuner skills apply {r['id']}"} for r in rows]


def load_history(conn: sqlite3.Connection, with_effect: bool = True
                 ) -> list[dict]:
    """All recorded skill proposals/changes, newest first."""
    rows = conn.execute(f"SELECT {COLUMNS} FROM skill_changes "
                        "ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if with_effect and d["status"] == "applied":
            d["effectiveness"] = evaluate(conn, d)
        out.append(d)
    return out
