"""Platform-aware locations for Tuner config, data, and reports.

`TUNER_HOME` overrides everything (used by tests and portable installs).
`TUNER_FAKE_HOME` overrides the user home that collectors scan (tests).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP = "tuner"


def user_home() -> Path:
    """Return the home directory that agent data is discovered under."""
    return Path(os.environ.get("TUNER_FAKE_HOME") or Path.home())


def _platform_dirs() -> tuple[Path, Path]:
    """Return (config_dir, data_dir) following platform conventions."""
    home = user_home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / APP
        return base, base
    if sys.platform == "win32":
        roaming = Path(os.environ.get("APPDATA") or home / "AppData/Roaming")
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData/Local")
        return roaming / APP, local / APP
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    return cfg / APP, data / APP


def config_dir() -> Path:
    """Directory holding config.toml."""
    override = os.environ.get("TUNER_HOME")
    if override:
        return Path(override) / "config"
    return _platform_dirs()[0]


def data_dir() -> Path:
    """Directory holding the SQLite database, spool, caches, backups."""
    override = os.environ.get("TUNER_HOME")
    if override:
        return Path(override) / "data"
    return _platform_dirs()[1]


def config_file() -> Path:
    """Path of the TOML configuration file."""
    return config_dir() / "config.toml"


def db_file() -> Path:
    """Path of the SQLite database."""
    return data_dir() / "tuner.db"


def reports_dir() -> Path:
    """Directory containing dated report folders."""
    return data_dir() / "reports"


def spool_dir() -> Path:
    """Directory where hooks append events (never read by agents)."""
    return data_dir() / "spool"


def ensure_private_dir(path: Path) -> Path:
    """Create `path` (and parents) with owner-only permissions."""
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        try:
            path.chmod(0o700)
        except OSError:
            pass
    return path
