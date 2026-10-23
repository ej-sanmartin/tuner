"""`tuner analyze`: cache status, evidence, and saving analyses.

Tuner never runs a model. The /tuner skill has the current agent read
`evidence`, write an analysis, and submit it with `save`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tuner.analysis import service, store
from tuner.analysis.schema_doc import TEMPLATE
from tuner.analysis.validate import AnalysisError
from tuner.commands.common import TunerError, emit_json, load_config, open_db
from tuner.reports.generate import render_report, report_dir
from tuner.reports.opener import latest_report_dir


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("analyze", help="evidence-backed analysis (cached)")
    p.add_argument("action", nargs="?", default="status", choices=(
        "status", "evidence", "schema", "save", "show", "refresh", "list",
        "clear"))
    p.add_argument("file", nargs="?", help="analysis JSON for `save` "
                   "(or - for stdin)")
    p.add_argument("--period", help="report period id (default: latest)")
    p.add_argument("--top", type=int, help="analyze the top N tasks")
    p.add_argument("--task", action="append", help="analyze this task id")
    p.add_argument("--agent", default="unknown",
                   help="agent that produced the analysis")
    p.add_argument("--model", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def _plan(conn, cfg, args):
    """Resolve the report directory and compute the analysis plan."""
    directory = report_dir(args.period) if args.period \
        else latest_report_dir(conn)
    if directory is None:
        raise TunerError("no report yet; run `tuner report` first")
    try:
        return service.make_plan(conn, cfg, directory, args.top, args.task)
    except service.NoReport as exc:
        raise TunerError(str(exc)) from exc


def _status(conn, plan, args) -> int:
    """Report cache state; never claims an analysis ran when it did not."""
    state = store.status(conn, plan.period_id, plan.key)
    info = {"period": plan.period_id, "status": state,
            "cache_key": plan.key, "tasks_selected": len(plan.selection),
            "analysis_file": str(store.current_file(plan.period_id))
            if state == "valid" else None,
            "next": {"valid": "reuse cached analysis (tuner analyze show)",
                     "stale": "inputs changed; re-run /tuner analysis",
                     "missing": "not analyzed; run /tuner in your agent"
                     }[state]}
    if args.json:
        emit_json(info)
    else:
        print(f"period {info['period']}: analysis {state} "
              f"({info['tasks_selected']} tasks) -> {info['next']}")
    return 0


def _save(conn, cfg, plan, args) -> int:
    """Validate and store a submitted analysis."""
    if not args.file:
        raise TunerError("usage: tuner analyze save FILE|-")
    text = sys.stdin.read() if args.file == "-" \
        else Path(args.file).read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise TunerError(f"analysis is not valid JSON: {exc}") from exc
    if isinstance(raw, dict) and raw.get("cache_key") not in (None,
                                                              plan.key):
        raise TunerError("analysis was produced for different inputs "
                         "(cache_key mismatch); rerun `tuner analyze "
                         "evidence` and analyse again")
    producer = {"agent": args.agent, "model": args.model}
    try:
        analysis, warnings = service.save_analysis(conn, cfg, plan, raw,
                                                   producer)
    except AnalysisError as exc:
        for problem in exc.problems:
            print(f"invalid: {problem}", file=sys.stderr)
        raise TunerError("analysis rejected; fix the problems above") \
            from exc
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    cov = analysis["coverage"]
    print(f"saved analysis ({cov['analyzed']}/{cov['selected']} tasks, "
          f"{len(analysis['recommendations'])} recommendations) -> "
          f"{store.current_file(plan.period_id)}")
    return 0


def _show(plan) -> int:
    """Print the stored analysis for the period."""
    path = store.current_file(plan.period_id)
    if not path.exists():
        raise TunerError("no analysis for this period; run /tuner")
    emit_json(json.loads(path.read_text(encoding="utf-8")))
    return 0


def run(args) -> int:
    """Dispatch analyze actions."""
    cfg = load_config()
    conn = open_db()
    if args.action == "schema":
        emit_json(TEMPLATE)
        return 0
    if args.action == "list":
        rows = conn.execute("SELECT period_id, created_at, status, "
                            "cache_key FROM analyses ORDER BY created_at "
                            "DESC").fetchall()
        for r in rows:
            print(f"{r['created_at']}  {r['period_id']}  {r['status']:<11}"
                  f" {r['cache_key'][:12]}")
        return 0
    if args.action == "clear":
        print(f"invalidated {store.invalidate(conn)} analysis(es)")
        return 0
    plan = _plan(conn, cfg, args)
    if args.action == "refresh":
        store.invalidate(conn, plan.period_id)
        render_report(conn, plan.directory, plan.usage,
                      plan.snapshot_hash, cfg.skills.track_effectiveness)
        print("cached analysis invalidated; run /tuner to recompute")
        return 0
    if args.action == "evidence":
        emit_json(service.bundle(conn, cfg, plan))
        return 0
    if args.action == "save":
        return _save(conn, cfg, plan, args)
    if args.action == "show":
        return _show(plan)
    return _status(conn, plan, args)
