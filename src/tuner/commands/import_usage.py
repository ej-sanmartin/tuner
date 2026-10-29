"""`tuner import cursor`: reconcile estimates with dashboard usage."""

from __future__ import annotations

from pathlib import Path

from tuner.commands.common import TunerError, open_db
from tuner.dashboard.csv import (
    match_requests,
    parse_csv,
    reconcile_status,
    replace_snapshot,
)
from tuner.dashboard.fetch import download


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser(
        "import", help="reconcile estimates with a dashboard export")
    s = p.add_subparsers(dest="source")
    c = s.add_parser("cursor", help="Cursor usage CSV (one row per request)")
    c.add_argument("file", nargs="?", help="CSV from the Cursor dashboard")
    c.add_argument(
        "--fetch", action="store_true",
        help="download the CSV from cursor.com with the local session "
             "token (the token is sent to cursor.com)")
    p.set_defaults(func=run)


def run(args) -> int:
    """Import a CSV or fetch one, then print the match result."""
    if getattr(args, "source", None) != "cursor":
        raise TunerError("usage: tuner import cursor <file> "
                         "or tuner import cursor --fetch")
    if bool(args.file) == bool(args.fetch):
        raise TunerError("pass a CSV file or --fetch, not both")
    if args.fetch:
        text = download()
    else:
        path = Path(args.file)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise TunerError(f"cannot read {path}: {exc}") from exc
    try:
        rows, skipped = parse_csv(text)
    except ValueError as exc:
        raise TunerError(str(exc)) from exc
    if not rows:
        raise TunerError("the CSV has no usage rows")
    conn = open_db()
    match_requests(conn, rows)
    replace_snapshot(conn, rows)
    st = reconcile_status(conn)
    print(st["detail"])
    if skipped:
        print(f"{skipped} row(s) skipped (unreadable)")
    print("matched turns now use the dashboard numbers in reports; "
          "other Cursor turns stay estimated")
    return 0
