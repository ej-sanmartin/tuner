"""`tuner schedule`: install/inspect the OS job or run due reports."""

from __future__ import annotations

from datetime import UTC, datetime

from tuner.commands.common import TunerError, load_config, open_db
from tuner.integrations.exe import tuner_argv
from tuner.scheduler import get_scheduler, local_spec
from tuner.scheduler.runner import run_due


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("schedule", help="manage scheduled reports")
    s = p.add_subparsers(dest="action")
    s.add_parser("install", help="register the OS scheduled job")
    s.add_parser("uninstall", help="remove the OS scheduled job")
    s.add_parser("status", help="show scheduler state and due periods")
    r = s.add_parser("run", help="generate any due reports (idempotent)")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--now", help="override current time (ISO, for testing)")
    p.set_defaults(func=run)


def install_job(cfg) -> str:
    """Register the OS job from configuration; returns its location."""
    r = cfg.report
    spec = local_spec(r.period, r.day, r.time, r.timezone)
    return get_scheduler().install(spec, tuner_argv())


def run(args) -> int:
    """Dispatch schedule actions."""
    cfg = load_config()
    action = args.action or "status"
    sched = get_scheduler()
    if action == "install":
        print(f"scheduled job registered: {install_job(cfg)}")
        r = cfg.report
        print(f"fires {r.period} ({r.day if r.period == 'weekly' else ''} "
              f"{r.time} {r.timezone}); catches up on login/wake")
    elif action == "uninstall":
        print("removed" if sched.uninstall() else "no scheduled job found")
    elif action == "status":
        st = sched.status()
        print(st)
        conn = open_db()
        from tuner.scheduler.runner import due
        pending = [p.id for p in due(conn, cfg, datetime.now(UTC))]
        print(f"due periods: {pending or 'none'}")
    elif action == "run":
        now = datetime.fromisoformat(args.now).astimezone(UTC) \
            if args.now else None
        try:
            results = run_due(open_db(), cfg, now, dry_run=args.dry_run)
        except OSError as exc:
            raise TunerError(str(exc)) from exc
        verb = "would generate" if args.dry_run else "generated"
        for res in results:
            print(f"{verb} {res.period_id}: {res.html_path}")
        if not results:
            print("nothing due")
    return 0
