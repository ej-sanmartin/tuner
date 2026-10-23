"""`tuner init`: one-time, idempotent, explicit setup."""

from __future__ import annotations

from tuner import config as config_mod
from tuner import paths
from tuner.collectors.cursor_paths import cursor_home
from tuner.commands.common import TunerError, load_config, open_db
from tuner.integrations import cursor_hooks, skill_install


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("init", help="set up config, hooks, skill, schedule")
    p.add_argument("--no-hooks", action="store_true",
                   help="do not install Cursor hooks")
    p.add_argument("--no-skill", action="store_true",
                   help="do not install the /tuner skill")
    p.add_argument("--no-schedule", action="store_true",
                   help="do not register the scheduled job")
    p.add_argument("--no-collect", action="store_true",
                   help="skip the first collection")
    p.set_defaults(func=run)


def _step(label: str, fn) -> None:
    """Run one setup step, reporting failure without aborting others."""
    try:
        print(f"  ok    {label}: {fn()}")
    except (TunerError, OSError, RuntimeError) as exc:
        print(f"  skip  {label}: {exc}")


def run(args) -> int:
    """Create config/dirs and install optional integrations."""
    print("Tuner setup (everything stays on this machine):")
    paths.ensure_private_dir(paths.data_dir())
    created = config_mod.write_default()
    print(f"  ok    config: {paths.config_file()}"
          f"{' (created)' if created else ' (kept existing)'}")
    cfg = load_config()
    open_db().close()
    if not args.no_hooks:
        if cursor_home().exists():
            _step("cursor hooks", lambda: ", ".join(
                cursor_hooks.install()) or "already installed")
        else:
            print("  skip  cursor hooks: Cursor not found")
    if not args.no_skill:
        _step("/tuner skill", lambda: str(
            skill_install.install(cfg.skills.skill_dir)))
    if not args.no_schedule:
        from tuner.commands.schedule import install_job
        _step("schedule", lambda: install_job(cfg))
    from tuner.integrations.sync import mark_synced
    mark_synced(open_db())
    if not args.no_collect:
        from tuner.commands.collect import run_collect
        stats = run_collect(quiet=True)
        print(f"  ok    first collection: {stats.parsed} file(s), "
              f"{stats.tasks_written} task(s), {stats.failed} failed, "
              f"{stats.seconds:.1f}s")
    print("Next: `tuner report --open`, then run /tuner in your agent. "
          "Undo everything with `tuner uninstall`.")
    return 0
