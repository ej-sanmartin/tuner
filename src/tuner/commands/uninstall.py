"""`tuner uninstall`: remove only what Tuner itself installed."""

from __future__ import annotations

import shutil

from tuner import paths
from tuner.commands.common import load_config
from tuner.integrations import cursor_hooks, skill_install


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("uninstall", help="remove hooks, skill, schedule")
    p.add_argument("--purge-data", action="store_true",
                   help="also delete the database, reports, and config")
    p.set_defaults(func=run)


def run(args) -> int:
    """Remove managed integrations; optionally delete local data."""
    from tuner.scheduler import get_scheduler
    cfg = load_config()
    removed = cursor_hooks.uninstall()
    print(f"cursor hooks removed: {', '.join(removed) or 'none'}")
    gone = skill_install.uninstall(cfg.skills.skill_dir)
    print(f"/tuner skill removed: {'yes' if gone else 'none managed'}")
    print("scheduled job removed: "
          f"{'yes' if get_scheduler().uninstall() else 'none found'}")
    print("Skills Tuner created for you are left in place; roll them back "
          "first with `tuner skills rollback ID` if you want them gone.")
    if args.purge_data:
        for d in {paths.data_dir(), paths.config_dir()}:
            shutil.rmtree(d, ignore_errors=True)
            print(f"deleted {d}")
    else:
        print(f"data kept at {paths.data_dir()} (use --purge-data)")
    return 0
