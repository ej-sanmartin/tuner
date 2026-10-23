"""Orchestrates analysis: plan (cache key), evidence, save, proposals.

Tuner never calls a model itself. An agent (via the /tuner skill) reads
the evidence and submits an analysis, which this module validates,
stores, links to skill proposals, and renders into the report.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from tuner.analysis import evidence, keys, store, validate
from tuner.config import Config
from tuner.reports import generate as gen
from tuner.skills import lifecycle
from tuner.skills.placement import PlacementError


class NoReport(RuntimeError):
    """No usage.json exists for the requested period."""


@dataclass
class Plan:
    """What an analysis would cover and its cache identity."""

    period_id: str
    directory: Path
    usage: dict
    snapshot_hash: str
    selection: list[str]
    key: str


def make_plan(conn: sqlite3.Connection, cfg: Config, directory: Path,
              top_n: int | None = None, task_ids: list[str] | None = None
              ) -> Plan:
    """Compute selection + cache key for the report in `directory`."""
    try:
        usage = json.loads((directory / "usage.json").read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise NoReport(f"no usage.json in {directory}; run `tuner report`"
                       ) from exc
    digest = gen.content_hash(usage)
    selection = keys.task_selection(usage, top_n, task_ids)
    key = keys.cache_key(digest, selection, usage, cfg)
    return Plan(usage["period"]["id"], directory, usage, digest, selection,
                key)


def bundle(conn: sqlite3.Connection, cfg: Config, plan: Plan) -> dict:
    """Redacted evidence for the planned tasks."""
    return evidence.build_bundle(conn, cfg, plan.usage, plan.snapshot_hash,
                                 plan.key, plan.selection)


def _link_proposals(conn: sqlite3.Connection, cfg: Config, plan: Plan,
                    analysis: dict) -> None:
    """Create skill proposals for recommendations carrying a change."""
    by_id = {t["id"]: t for t in plan.usage["tasks"]}
    for rec in analysis["recommendations"]:
        sc = rec.pop("skill_change", None)
        rec["status"] = "advice"
        if not sc:
            continue
        tasks = sorted({e["task_id"] for e in rec["evidence"]})
        finding = {"analysis_key": plan.key, "recommendation": rec["id"],
                   "title": rec["title"], "tasks": tasks,
                   "repos": sorted({by_id[t]["repo"] for t in tasks
                                    if by_id[t]["repo"]})}
        prior = lifecycle.existing(conn, plan.key, rec["id"])
        if prior:  # idempotent re-save of the same analysis
            rec.update(status=prior["status"], change_id=prior["id"],
                       destination=prior["path"],
                       diff=lifecycle.show_diff(conn, prior["id"]))
            continue
        try:
            p = lifecycle.propose(conn, cfg, {**sc, "scope": rec["scope"]
                                              if rec["scope"] != "none"
                                              else None}, finding)
        except (lifecycle.SkillError, PlacementError) as exc:
            rec["status"], rec["note"] = "rejected_by_policy", str(exc)
            continue
        rec.update(status=p.status, change_id=p.id,
                   destination=str(p.path), diff=p.diff,
                   warnings=p.warnings)


def save_analysis(conn: sqlite3.Connection, cfg: Config, plan: Plan,
                  raw: dict, producer: dict) -> tuple[dict, list[str]]:
    """Validate, create proposals, store, and refresh the HTML report."""
    refs = validate.valid_refs(conn, plan.usage, plan.selection)
    analysis, warnings = validate.validate(
        raw, plan.usage, plan.selection, plan.snapshot_hash, plan.key,
        refs, producer)
    _link_proposals(conn, cfg, plan, analysis)
    store.save(conn, analysis, plan.selection)
    gen.render_report(conn, plan.directory, plan.usage, plan.snapshot_hash,
                       cfg.skills.track_effectiveness)
    return analysis, warnings
