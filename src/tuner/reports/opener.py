"""Find and open reports with the platform default or Cursor."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


def latest_report_dir(conn) -> Path | None:
    """Directory of the report written most recently, any status."""
    row = conn.execute(
        "SELECT report_dir FROM report_periods ORDER BY "
        "generated_at DESC, period_end DESC LIMIT 1").fetchone()
    return Path(row["report_dir"]) if row else None


def scheduled_report_dir(conn) -> Path | None:
    """Directory of the latest finished scheduled period.

    Complete rows are scheduled windows. Partial rows are custom
    windows and in-progress periods.
    """
    row = conn.execute(
        "SELECT report_dir FROM report_periods WHERE status='complete' "
        "ORDER BY period_end DESC, generated_at DESC LIMIT 1").fetchone()
    return Path(row["report_dir"]) if row else None


def report_to_open(conn, generated: bool = False
                   ) -> tuple[Path | None, str | None]:
    """(directory, note) for `tuner open`.

    The default is the latest finished period. `generated` selects the
    file written most recently. With no finished period, the newest
    file is used and `note` says so.
    """
    if generated:
        return latest_report_dir(conn), None
    scheduled = scheduled_report_dir(conn)
    if scheduled is not None:
        return scheduled, None
    latest = latest_report_dir(conn)
    if latest is None:
        return None, None
    return latest, ("no finished scheduled report; "
                    "opening the latest generated one")


def open_file(path: Path, opener: str = "default") -> str:
    """Open `path`; returns a short description of what was used."""
    if opener == "cursor":
        exe = shutil.which("cursor")
        if exe:
            subprocess.Popen([exe, str(path)])  # noqa: S603
            return "cursor"
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Cursor", str(path)])  # noqa
            return "cursor"
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603, S607
        return "default browser"
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
        return "default browser"
    if webbrowser.open(path.as_uri()):
        return "default browser"
    raise RuntimeError("no way to open a browser; open the file manually")
