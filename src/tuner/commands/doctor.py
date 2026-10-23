"""`tuner doctor`: diagnose setup and data sources."""

from __future__ import annotations

import shutil
import sys
from datetime import UTC, datetime

from tuner import paths
from tuner.collectors import build_collectors
from tuner.commands.common import TunerError, emit_json, load_config, open_db
from tuner.integrations import cursor_hooks, skill_install
from tuner.pricing import PriceBook
from tuner.scheduler import runner
from tuner.scheduler.base import CHECK_INTERVAL_S
from tuner.storage import repo

OK, WARN, FAIL = "ok", "warn", "fail"


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("doctor", help="check setup and data sources")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def checks() -> list[dict]:
    """Run all diagnostics; each is {name, status, detail}."""
    out: list[dict] = []

    def add(name: str, status: str, detail: str) -> None:
        out.append({"name": name, "status": status, "detail": detail})

    add("python", OK if sys.version_info >= (3, 13) else FAIL,
        sys.version.split()[0])
    try:
        cfg = load_config()
        add("config", OK, str(paths.config_file()))
    except TunerError as exc:
        add("config", FAIL, str(exc))
        return out
    conn = open_db()
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    add("database", OK, f"{paths.db_file()} (schema v{ver})")
    last = repo.kv_get(conn, "last_collect")
    add("last collection", OK if last else WARN, last or "never; run "
        "`tuner collect`")
    from tuner.integrations.sync import needs_sync
    old = needs_sync(conn)
    add("integrations", OK if old is None else WARN,
        "in sync" if old is None else f"last synced by {old}; "
        "run `tuner upgrade --sync-only`")
    from tuner.commands.upgrade import install_method
    kind, where = install_method()
    protected = [str(paths.user_home() / d) for d in
                 ("Documents", "Desktop", "Downloads")]
    risky = (sys.platform == "darwin" and kind.startswith("editable")
             and where.startswith(tuple(protected)))
    add("install", WARN if risky else OK, f"{kind}: {where}" + (
        "; launchd cannot read protected folders, so the scheduled job "
        "would hang. Reinstall non-editable: `uv tool install --force "
        "--reinstall <dir>`" if risky else ""))
    errs = conn.execute("SELECT COUNT(*) FROM collection_errors").fetchone()[0]
    add("collection errors", OK if not errs else WARN, str(errs))
    for c in build_collectors(cfg):
        found = c.discover()
        add(f"source: {c.name}", OK if found else WARN,
            "; ".join(str(p) for p in c.locations()) if found
            else "no data found")
        if c.name == "cursor":
            ev = cursor_hooks.installed_events()
            add("cursor hooks", OK if ev else WARN,
                f"{len(ev)} events" if ev else "not installed "
                "(timestamps/compaction less precise); `tuner init`")
    sk = skill_install.target_dir(cfg.skills.skill_dir)
    add("/tuner skill", OK if skill_install.is_managed(sk) else WARN,
        str(sk) if sk.exists() else "not installed; `tuner init`")
    from tuner.scheduler import get_scheduler
    st = get_scheduler().status()
    add("schedule", OK if st.get("installed") else WARN,
        st.get("path") or st.get("note", "not installed; `tuner schedule "
                                         "install`"))
    now = datetime.now(UTC)
    late = [p.id for p in runner.due(conn, cfg, now)
            if (now - p.end).total_seconds() > 2 * CHECK_INTERVAL_S]
    last = repo.kv_get(conn, "last_schedule_run")
    add("scheduled runs", WARN if late else OK,
        f"last run {last or 'never'}" + (
            f"; {len(late)} report(s) overdue ({late[0]}...): the OS timer "
            "may not be firing. Run `tuner schedule run` (it also runs at "
            "login and when Cursor is used)" if late else ""))
    meta = PriceBook().meta
    add("pricing", OK, f"{meta.get('source', 'bundled')} "
        f"{meta.get('fetched_at', '')}")
    notifier = shutil.which("osascript" if sys.platform == "darwin"
                            else "powershell" if sys.platform == "win32"
                            else "notify-send")
    add("notifications", OK if notifier else WARN,
        notifier or "no notifier found; reports still work")
    return out


def run(args) -> int:
    """Print diagnostics; non-zero exit when something failed."""
    results = checks()
    if args.json:
        emit_json(results)
    else:
        for r in results:
            print(f"{r['status']:<5} {r['name']:<20} {r['detail']}")
    return 1 if any(r["status"] == FAIL for r in results) else 0
