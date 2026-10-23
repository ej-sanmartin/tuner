"""Find and open reports with the platform default or Cursor."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


def latest_report_dir(conn) -> Path | None:
    """Directory of the most recently generated complete report."""
    row = conn.execute(
        "SELECT report_dir FROM report_periods ORDER BY "
        "(status='complete') DESC, period_end DESC, generated_at DESC "
        "LIMIT 1").fetchone()
    return Path(row["report_dir"]) if row else None


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
