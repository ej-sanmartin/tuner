"""`tuner open`: open the latest report."""

from __future__ import annotations

from tuner.commands.common import TunerError, load_config, open_db
from tuner.reports.opener import latest_report_dir, open_file


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("open", help="open the latest report")
    p.add_argument("--cursor", action="store_true",
                   help="open in Cursor instead of the default browser")
    p.add_argument("--path", action="store_true",
                   help="print the path instead of opening")
    p.set_defaults(func=run)


def run(args) -> int:
    """Open or print the latest report path."""
    cfg = load_config()
    directory = latest_report_dir(open_db())
    if directory is None or not (directory / "report.html").exists():
        raise TunerError("no report yet; run `tuner report` first")
    target = directory / "report.html"
    if args.path:
        print(target)
        return 0
    opener = "cursor" if args.cursor else cfg.delivery.opener
    print(f"opening {target} with {open_file(target, opener)}")
    return 0
