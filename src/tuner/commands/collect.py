"""`tuner collect`: incremental import of local agent usage."""

from __future__ import annotations

from dataclasses import asdict

from tuner.collect import collect
from tuner.collectors import build_collectors
from tuner.commands.common import (
    emit_json,
    load_config,
    open_db,
    parse_since,
)


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("collect", help="import local usage (no LLM)")
    p.add_argument("--since", help="only files modified since (7d, 36h, ISO)")
    p.add_argument("--full", action="store_true",
                   help="re-parse every file, ignoring change detection")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run_collect(args=None, quiet: bool = False):
    """Run collection with config defaults; returns CollectStats."""
    cfg = load_config()
    conn = open_db()
    since = parse_since(getattr(args, "since", None))
    full = bool(getattr(args, "full", False))
    return collect(conn, build_collectors(cfg), cfg, since, full,
                   lock_timeout=30.0)


def run(args) -> int:
    """Execute and summarise."""
    stats = run_collect(args)
    if args.json:
        emit_json(asdict(stats))
        return 0
    for msg in stats.messages:
        print(msg)
    print(f"files seen {stats.seen}: parsed {stats.parsed}, "
          f"unchanged {stats.skipped}, failed {stats.failed} "
          f"({stats.seconds}s)")
    for agent, info in stats.agents.items():
        print(f"  {agent}: {info['parsed']} parsed, {info['skipped']} "
              f"unchanged, {info['failed']} failed")
    if stats.tasks_written:
        print(f"tasks regrouped: {stats.tasks_written}")
    return 0
