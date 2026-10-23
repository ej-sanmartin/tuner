"""`tuner report`: deterministic usage snapshot + HTML report."""

from __future__ import annotations

from datetime import UTC, datetime

from tuner.commands.collect import run_collect
from tuner.commands.common import (
    TunerError,
    emit_json,
    load_config,
    open_db,
    parse_since,
)
from tuner.reports import generate as gen
from tuner.reports import periods
from tuner.reports.aggregate import total_of  # noqa: F401  (re-export)
from tuner.reports.opener import open_file


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("report", help="generate usage.json + report.html")
    p.add_argument("--top", type=int, help="top N tasks (default: config)")
    p.add_argument("--current", action="store_true",
                   help="in-progress period instead of the last completed")
    p.add_argument("--since", help="custom period start (ISO or 7d)")
    p.add_argument("--until", help="custom period end (ISO)")
    p.add_argument("--no-collect", action="store_true",
                   help="skip the incremental collection step")
    p.add_argument("--open", action="store_true", help="open when done")
    p.add_argument("--json", action="store_true",
                   help="print the usage snapshot JSON to stdout")
    p.set_defaults(func=run)


def choose_period(cfg, args, now: datetime) -> periods.Period:
    """Select the reporting period from CLI flags and config."""
    r = cfg.report
    if args.since or args.until:
        start = parse_since(args.since) or datetime.fromtimestamp(0, UTC)
        end = parse_since(args.until) or now
        pid = f"custom-{start:%Y%m%d}-{end:%Y%m%d}"
        return periods.Period(pid, start, end, r.timezone, partial=True)
    fn = periods.current_period if args.current else periods.completed_period
    return fn(now, r.period, r.day, r.time, r.timezone)


def print_summary(usage: dict, path) -> None:
    """Human-readable terminal summary."""
    o, p = usage["overview"], usage["period"]
    print(f"Period {p['id']}  {p['start'][:10]} → {p['end'][:10]} "
          f"({p['timezone']})")
    q = o["quality"]
    print(f"Tokens {o['tokens']['total']:,}  [{q['measurement']}, "
          f"{q['confidence']} confidence]  tasks {o['counts']['tasks']}  "
          f"repos {o['counts']['repositories']}")
    cost = o.get("cost")
    if cost:
        flag = "" if cost["complete"] else " (incomplete: unknown rates)"
        print(f"Est. API-equivalent cost ${cost['usd']:.2f}{flag}")
    top = usage["selection"]["top_n"]
    for t in usage["tasks"][:top]:
        print(f" #{t['rank']} {t['tokens']['total']:>14,} "
              f"{t['quality']['measurement']:<9} {t['agent']:<11} "
              f"{(t['repo'] or '-')[:18]:<18} {t['title'][:50]}")
    print(f"Report: {path}")


def run(args) -> int:
    """Collect (unless skipped), then generate the report."""
    cfg = load_config()
    if args.top is not None and args.top < 1:
        raise TunerError("--top must be >= 1")
    if not args.no_collect:
        run_collect()
    conn = open_db()
    now = datetime.now(UTC)
    period = choose_period(cfg, args, now)
    result = gen.generate(conn, cfg, period, args.top, now)
    if args.json:
        emit_json(result.usage)
    else:
        print_summary(result.usage, result.html_path)
    if args.open or cfg.delivery.open_automatically:
        open_file(result.html_path, cfg.delivery.opener)
    return 0
