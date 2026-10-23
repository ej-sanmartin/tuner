"""Shared helpers for CLI commands."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import UTC, datetime, timedelta

from tuner import config as config_mod
from tuner.config import Config, ConfigError
from tuner.storage import connect


class TunerError(RuntimeError):
    """A user-facing error (printed without a traceback)."""


def load_config() -> Config:
    """Load configuration, printing non-fatal warnings to stderr."""
    try:
        cfg = config_mod.load()
    except ConfigError as exc:
        raise TunerError(str(exc)) from exc
    for warning in cfg.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return cfg


def open_db() -> sqlite3.Connection:
    """Open the Tuner database."""
    return connect()


def parse_since(text: str | None, now: datetime | None = None
                ) -> datetime | None:
    """Parse '7d', '36h', or an ISO date/time into an aware datetime."""
    if not text:
        return None
    now = now or datetime.now(UTC)
    m = re.fullmatch(r"(\d+)([dhw])", text.strip())
    if m:
        unit = {"d": "days", "h": "hours", "w": "weeks"}[m.group(2)]
        return now - timedelta(**{unit: int(m.group(1))})
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TunerError(f"cannot parse time {text!r}") from exc
    return dt if dt.tzinfo else dt.astimezone()


def emit_json(obj: object) -> None:
    """Print JSON to stdout."""
    print(json.dumps(obj, indent=2, default=str))
