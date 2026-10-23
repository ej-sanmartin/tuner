"""`tuner skills`: review, apply, diff, roll back skill changes."""

from __future__ import annotations

from tuner.commands.common import TunerError, emit_json, load_config, open_db
from tuner.skills import discover, lifecycle
from tuner.skills.history import load_history


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("skills", help="review and apply skill changes")
    s = p.add_subparsers(dest="action")
    ls = s.add_parser("list", help="proposals/changes and managed skills")
    ls.add_argument("--json", action="store_true")
    for name, text in (("diff", "show the proposed diff"),
                       ("apply", "apply a proposal (backup + conflict check)"),
                       ("reject", "dismiss a proposal"),
                       ("rollback", "undo an applied change")):
        c = s.add_parser(name, help=text)
        c.add_argument("id")
        if name == "rollback":
            c.add_argument("--force", action="store_true",
                           help="overwrite edits made after applying")
    s.add_parser("discover", help="all skills Cursor/Claude Code can see")
    p.set_defaults(func=run)


def _list(args, conn) -> None:
    """Print history (and managed skills)."""
    rows = load_history(conn)
    if args.json:
        emit_json(rows)
        return
    if not rows:
        print("no skill proposals or changes yet")
    for r in rows:
        eff = r.get("effectiveness", {}).get("verdict", "")
        print(f"{r['id']}  {r['status']:<11} {r['action']:<7} "
              f"{r['scope']:<7} {r['skill_name']:<28} {eff}")


def run(args) -> int:
    """Dispatch skills actions."""
    cfg = load_config()
    conn = open_db()
    action = args.action or "list"
    try:
        if action == "list":
            args.json = getattr(args, "json", False)
            _list(args, conn)
        elif action == "discover":
            roots = list(discover.known_repo_roots(conn).values())
            for s in discover.discover(roots):
                flag = "managed" if s.managed else s.scope
                print(f"{flag:<8} {s.name:<28} {s.file}")
        elif action == "diff":
            print(lifecycle.show_diff(conn, args.id) or "(no changes)")
        elif action == "apply":
            if cfg.skills.mode == "suggest":
                raise TunerError("skills.mode is 'suggest' (apply is "
                                 "disabled); set it to 'review' first")
            print(f"applied -> {lifecycle.apply(conn, args.id)}")
        elif action == "reject":
            lifecycle.reject(conn, args.id)
            print("rejected")
        elif action == "rollback":
            lifecycle.rollback(conn, args.id, args.force)
            print("rolled back")
    except lifecycle.SkillError as exc:
        raise TunerError(str(exc)) from exc
    return 0
