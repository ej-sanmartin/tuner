"""Validated TOML configuration with defaults.

The schema below drives validation, defaults, `tuner config` output, and
in-place edits that preserve the user's comments and unknown keys.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from tuner import paths
from tuner.fsutil import atomic_write_text

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday")


class ConfigError(ValueError):
    """Raised when a configuration value is invalid."""


@dataclass(frozen=True)
class Opt:
    """One configuration option: type, default, optional constraints."""

    kind: str  # bool | int | str | choice | list
    default: Any
    choices: tuple[str, ...] = ()
    lo: int = 0
    hi: int = 0


SCHEMA: dict[str, dict[str, Opt]] = {
    "report": {
        "top_n": Opt("int", 3, lo=1, hi=50),
        "period": Opt("choice", "weekly",
                      ("daily", "weekly", "monthly")),
        "day": Opt("choice", "sunday", DAYS),
        "time": Opt("str", "18:00"),
        "timezone": Opt("str", "local"),
        "catch_up": Opt("bool", True),
        "run_on_activity": Opt("bool", True),
        "backfill_limit": Opt("int", 4, lo=0, hi=52),
    },
    "sources": {
        "cursor": Opt("bool", True),
        "claude_code": Opt("bool", True),
        "repositories": Opt("str", "auto"),
        "cursor_state_db": Opt("bool", True),
        "extra_claude_dirs": Opt("list", []),
    },
    "attribution": {
        "merge_followups": Opt("bool", True),
        "followup_max_chars": Opt("int", 80, lo=0, hi=500),
        "idle_gap_minutes": Opt("int", 240, lo=1, hi=10080),
    },
    "analysis": {
        "cache": Opt("bool", True),
        "cost_estimation": Opt("bool", True),
    },
    "skills": {
        "mode": Opt("choice", "review", ("suggest", "review", "auto")),
        "scope": Opt("choice", "auto", ("auto", "global", "project")),
        "track_effectiveness": Opt("bool", True),
        "skill_dir": Opt("str", ".claude/skills"),
    },
    "delivery": {
        "notification": Opt("bool", True),
        "open_automatically": Opt("bool", False),
        "format": Opt("choice", "html", ("html",)),
        "opener": Opt("choice", "default", ("default", "cursor")),
    },
    "privacy": {
        "local_only": Opt("bool", True),
        "analysis_excerpts": Opt("bool", True),
        "redact_patterns": Opt("list", []),
    },
}

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _check(section: str, key: str, opt: Opt, value: Any) -> Any:
    """Validate and normalise one value; raise ConfigError on mismatch."""
    name = f"{section}.{key}"
    if opt.kind == "bool":
        if not isinstance(value, bool):
            raise ConfigError(f"{name} must be true or false")
    elif opt.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{name} must be an integer")
        if not opt.lo <= value <= opt.hi:
            raise ConfigError(f"{name} must be {opt.lo}..{opt.hi}")
    elif opt.kind == "choice":
        value = str(value).lower()
        if value not in opt.choices:
            raise ConfigError(f"{name} must be one of {list(opt.choices)}")
    elif opt.kind == "list":
        if not isinstance(value, list) or not all(
                isinstance(v, str) for v in value):
            raise ConfigError(f"{name} must be a list of strings")
    elif not isinstance(value, str):
        raise ConfigError(f"{name} must be a string")
    if name == "report.time" and not _TIME_RE.match(value):
        raise ConfigError("report.time must look like 18:00")
    if name == "report.timezone" and value != "local":
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ConfigError(f"report.timezone unknown: {value}") from exc
    if name == "sources.repositories" and value != "auto":
        raise ConfigError("sources.repositories supports only 'auto' for now")
    for pat in value if name == "privacy.redact_patterns" else []:
        try:
            re.compile(pat)
        except re.error as exc:
            raise ConfigError(
                f"invalid redact pattern {pat!r}: {exc}") from exc
    return value


@dataclass
class Config:
    """Typed view over validated settings plus any non-fatal warnings."""

    values: dict[str, dict[str, Any]]
    warnings: list[str] = field(default_factory=list)

    def __getattr__(self, section: str) -> SimpleNamespace:
        """Return a namespace for `section` (e.g. cfg.report.top_n)."""
        if section in SCHEMA:
            return SimpleNamespace(**self.values[section])
        raise AttributeError(section)


def defaults() -> dict[str, dict[str, Any]]:
    """Return a fresh copy of all default values."""
    return {s: {k: _copy(o.default) for k, o in opts.items()}
            for s, opts in SCHEMA.items()}


def _copy(value: Any) -> Any:
    """Copy mutable defaults (lists) so callers cannot alias them."""
    return list(value) if isinstance(value, list) else value


def parse(raw: dict[str, Any]) -> Config:
    """Merge raw TOML data over defaults, validating every known key."""
    values, warnings = defaults(), []
    for section, body in raw.items():
        if section not in SCHEMA or not isinstance(body, dict):
            warnings.append(f"unknown config section [{section}] ignored")
            continue
        for key, value in body.items():
            opt = SCHEMA[section].get(key)
            if opt is None:
                warnings.append(f"unknown key {section}.{key} ignored")
                continue
            values[section][key] = _check(section, key, opt, value)
    return Config(values, warnings)


def load(path: Path | None = None) -> Config:
    """Load config from disk, returning defaults when no file exists."""
    path = path or paths.config_file()
    if not path.exists():
        return Config(defaults())
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    return parse(raw)


def _literal(value: Any) -> str:
    """Render a Python value as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_literal(v) for v in value) + "]"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_defaults() -> str:
    """Render the full default configuration as commented TOML."""
    lines = ["# Tuner configuration. See docs/DEVELOPMENT.md for details."]
    for section, opts in SCHEMA.items():
        lines += ["", f"[{section}]"]
        lines += [f"{k} = {_literal(o.default)}" for k, o in opts.items()]
    return "\n".join(lines) + "\n"


def write_default(path: Path | None = None) -> bool:
    """Create the config file if missing. Returns True when created."""
    path = path or paths.config_file()
    if path.exists():
        return False
    paths.ensure_private_dir(path.parent)
    atomic_write_text(path, render_defaults())
    return True


def coerce(section: str, key: str, text: str) -> Any:
    """Convert CLI text into the typed value for `section.key`."""
    opt = SCHEMA.get(section, {}).get(key)
    if opt is None:
        raise ConfigError(f"unknown option {section}.{key}")
    if opt.kind == "bool":
        if text.lower() not in ("true", "false"):
            raise ConfigError(f"{section}.{key} must be true or false")
        value: Any = text.lower() == "true"
    elif opt.kind == "int":
        try:
            value = int(text)
        except ValueError as exc:
            raise ConfigError(f"{section}.{key} must be an integer") from exc
    elif opt.kind == "list":
        value = [p for p in (s.strip() for s in text.split(",")) if p]
    else:
        value = text
    return _check(section, key, opt, value)


def set_value(section: str, key: str, text: str,
              path: Path | None = None) -> Any:
    """Validate and persist one option, preserving the rest of the file."""
    path = path or paths.config_file()
    value = coerce(section, key, text)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_write_text(path, _edit(existing, section, key, _literal(value)))
    return value


def _edit(text: str, section: str, key: str, literal: str) -> str:
    """Replace or insert `key = literal` under `[section]` in `text`."""
    lines = text.splitlines()
    header = f"[{section}]"
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip() == header), None)
    if start is None:
        sep = [""] if lines else []
        return "\n".join(lines + sep + [header, f"{key} = {literal}"]) + "\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip().startswith("["):
            end = i
            break
    for i in range(start + 1, end):
        if re.match(rf"^\s*{re.escape(key)}\s*=", lines[i]):
            lines[i] = f"{key} = {literal}"
            return "\n".join(lines) + "\n"
    lines.insert(start + 1, f"{key} = {literal}")
    return "\n".join(lines) + "\n"
