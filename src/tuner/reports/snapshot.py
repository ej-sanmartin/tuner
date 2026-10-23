"""Build the deterministic `usage.json` snapshot (no LLM involved)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from tuner import SNAPSHOT_SCHEMA_VERSION, __version__
from tuner.config import Config
from tuner.pricing import PriceBook, estimate_cost
from tuner.reports import aggregate as agg
from tuner.reports import usage_query as uq
from tuner.reports.periods import Period
from tuner.reports.quality import data_quality

EFFECTIVE_TS = "COALESCE(t.ended_at, t.started_at, s.ended_at)"
DETAIL_FLOOR = 25  # tasks given full detail so the UI can vary top-N


def _period_tasks(conn: sqlite3.Connection, p: Period) -> list[sqlite3.Row]:
    """Tasks whose effective time falls inside the period."""
    return conn.execute(
        "SELECT t.*, s.agent, s.repo, s.project_path, s.native_id, "
        "s.source_path AS session_source, s.title AS session_title, "
        f"{EFFECTIVE_TS} AS eff_ts FROM tasks t JOIN sessions s "
        f"ON s.id = t.session_id WHERE {EFFECTIVE_TS} >= ? AND "
        f"{EFFECTIVE_TS} < ?", (p.start_iso, p.end_iso)).fetchall()


def _outcome(conn: sqlite3.Connection, task_id: str) -> str:
    """Outcome of the task's final turn."""
    row = conn.execute(
        "SELECT t.outcome FROM task_turns tt JOIN turns t ON "
        "t.id = tt.turn_id WHERE tt.task_id=? ORDER BY t.seq DESC LIMIT 1",
        (task_id,)).fetchone()
    return row["outcome"] if row else "unknown"


def _task_record(conn, row, rows, tools, events, grand_total, book,
                 with_cost: bool, detail: bool) -> dict:
    """Assemble one task entry from aggregated pieces."""
    tok = agg.totals(rows)
    sub_rows = [r for r in rows if r["via"] == "subagent"]
    evidence = json.loads(row["evidence_json"] or "{}")
    day = (row["eff_ts"] or "")[:10] or None
    rec = {
        "id": row["id"], "title": row["title"],
        "session_title": row["session_title"],
        "agent": row["agent"], "repo": row["repo"],
        "project_path": row["project_path"],
        "session_id": row["native_id"],
        "started_at": row["started_at"], "ended_at": row["ended_at"],
        "time_quality": row["time_quality"],
        "tokens": tok, "models": agg.by_model(rows),
        "share_of_total": round(tok["total"] / grand_total, 4)
        if grand_total else 0.0,
        "quality": agg.quality(rows),
        "outcome": _outcome(conn, row["id"]),
        "turns": len(evidence.get("turn_ids", [])),
        "grouping": {"boundary": row["boundary"],
                     "confidence": row["confidence"],
                     "merges": evidence.get("merges", [])},
        "tools": tools,
        "subagents": {"count": events["subagents"],
                      "tokens": agg.totals(sub_rows)["total"]},
        "compactions": events["compactions"],
        "sources": [{"path": row["session_source"],
                     "first_turn": (evidence.get("turn_ids") or [None])[0]}],
    }
    if with_cost:
        rec["cost"] = estimate_cost(agg.cost_inputs(rows), book, day)
    if detail:
        rec["timeline"] = uq.load_timeline(conn, row["id"])
    return rec


def build_snapshot(conn: sqlite3.Connection, cfg: Config, period: Period,
                   top_n: int | None = None,
                   now: datetime | None = None) -> dict:
    """Create the usage snapshot dict for `period`."""
    now = now or datetime.now(UTC)
    top_n = top_n or cfg.report.top_n
    book = PriceBook()
    with_cost = cfg.analysis.cost_estimation
    tasks = _period_tasks(conn, period)
    ids = [t["id"] for t in tasks]
    usage = uq.load_task_usage(conn, ids)
    all_rows = [r for t in ids for r in usage.get(t, [])]
    grand = agg.totals(all_rows)
    ranked = sorted(tasks, key=lambda t: (
        -agg.totals(usage.get(t["id"], []))["total"], t["id"]))
    detail_ids = [t["id"] for t in ranked[:max(top_n, DETAIL_FLOOR)]]
    tools = uq.load_task_tools(conn, detail_ids)
    events = uq.load_task_events(conn, detail_ids)
    records = []
    for rank, row in enumerate(ranked[:max(top_n, DETAIL_FLOOR)], start=1):
        rec = _task_record(conn, row, usage.get(row["id"], []),
                           tools[row["id"]], events[row["id"]],
                           grand["total"], book, with_cost, True)
        rec["rank"] = rank
        records.append(rec)
    overview = {
        "tokens": grand,
        "quality": agg.quality(all_rows),
        "counts": {
            "agents": len({t["agent"] for t in tasks}),
            "sessions": len({t["session_id"] for t in tasks}),
            "tasks": len(tasks),
            "repositories": len({t["repo"] for t in tasks if t["repo"]}),
        },
        "by_agent": _by_agent(tasks, usage),
        "by_model": agg.by_model(all_rows),
        "cost": estimate_cost(agg.cost_inputs(all_rows), book,
                              period.start_iso[:10]) if with_cost else None,
    }
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION, "kind": "tuner.usage",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tuner_version": __version__,
        "period": {"id": period.id, "start": period.start_iso,
                   "end": period.end_iso, "timezone": period.timezone,
                   "partial": period.partial,
                   "kind": cfg.report.period},
        "selection": {"top_n": top_n, "rank_by": "total_tokens",
                      "agents": sorted({t["agent"] for t in tasks}),
                      "repositories": sorted(
                          {t["repo"] for t in tasks if t["repo"]})},
        "overview": overview,
        "tasks": records,
        "data_quality": data_quality(conn, period, tasks, usage),
        "pricing": {"meta": book.meta, "enabled": with_cost},
        "privacy": {
            "contains": "redacted prompt previews (<=240 chars), tool "
                        "names, file paths/commands (redacted), counts",
            "excludes": "full prompts, responses, tool outputs, file "
                        "contents",
        },
    }


def _by_agent(tasks, usage) -> list[dict]:
    """Per-agent token totals and measurement status."""
    groups: dict[str, list[dict]] = {}
    for t in tasks:
        groups.setdefault(t["agent"], []).extend(usage.get(t["id"], []))
    return sorted(
        ({"agent": a, **agg.totals(rs),
          "measurement": agg.quality(rs)["measurement"],
          "tasks": sum(1 for t in tasks if t["agent"] == a)}
         for a, rs in groups.items()), key=lambda x: -x["total"])
