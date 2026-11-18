"""`tuner open`: open the latest finished scheduled report."""

from __future__ import annotations

import sys

from tuner.commands.common import TunerError, load_config, open_db
from tuner.reports.opener import open_file, report_to_open


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser(
        "open", help="open the latest finished scheduled report")
    p.add_argument("--generated", action="store_true",
                   help="open the report written most recently")
    p.add_argument("--cursor", action="store_true",
                   help="open in Cursor instead of the default browser")
    p.add_argument("--path", action="store_true",
                   help="print the path instead of opening")
    p.set_defaults(func=run)


def run(args) -> int:
    """Open or print a report. Default: latest finished period."""
    cfg = load_config()
    directory, note = report_to_open(open_db(), args.generated)
    if directory is None or not (directory / "report.html").exists():
        raise TunerError("no report yet; run `tuner report` first")
    if note:
        print(note, file=sys.stderr)
    target = directory / "report.html"
    if args.path:
        print(target)
        return 0
    opener = "cursor" if args.cursor else cfg.delivery.opener
    print(f"opening {target} with {open_file(target, opener)}")
    return 0
