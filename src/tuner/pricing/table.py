"""Layered price book: bundled snapshot < refreshed cache < user overrides.

User overrides (`pricing_overrides.toml` in the config dir) may carry
effective dates, enabling correct historical pricing:

    [[model]]
    id = "claude-sonnet-4"
    provider = "anthropic"
    effective_from = "2025-05-01"
    input = 3.0
    output = 15.0
    cache_write = 3.75
    cache_read = 0.30
    source = "https://docs.claude.com/en/docs/about-claude/pricing"
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from tuner import paths
from tuner.fsutil import atomic_write_text

_SUFFIX = re.compile(
    r"-(thinking|max|xhigh|high|medium|low|fast|1m|200k|preview|latest)$")
_DATE = re.compile(r"-(20\d{6}|\d{4}-\d{2}-\d{2})$")


@dataclass(frozen=True)
class Rate:
    """Per-million-token USD rates plus provenance."""

    model_id: str
    provider: str
    input: float | None
    output: float | None
    cache_write: float | None
    cache_read: float | None
    source: str
    effective_from: str | None = None
    fetched_at: str | None = None
    tiered: bool = False
    basis: str = "current_list_price"  # or "dated_override"


def normalize(model: str) -> list[str]:
    """Candidate lookup keys for a model name, most specific first."""
    name = model.strip().lower().split("/")[-1]
    out, seen = [], set()
    while name and name not in seen:
        seen.add(name)
        out.append(name)
        stripped = _DATE.sub("", _SUFFIX.sub("", name))
        name = stripped if stripped != name else ""
    return out


def cache_file() -> Path:
    """Where `tuner pricing refresh` stores the downloaded table."""
    return paths.data_dir() / "pricing" / "litellm.json"


def overrides_file() -> Path:
    """User-maintained dated overrides."""
    return paths.config_dir() / "pricing_overrides.toml"


def _bundled() -> dict:
    """Load the snapshot shipped with the package."""
    ref = resources.files("tuner.pricing") / "data" / "pricing_snapshot.json"
    return json.loads(ref.read_text(encoding="utf-8"))


def save_cache(table: dict) -> Path:
    """Persist a refreshed table atomically."""
    path = cache_file()
    atomic_write_text(path, json.dumps(table, indent=1, sort_keys=True))
    return path


class PriceBook:
    """Resolve (model, date) to a Rate, or None when unknown."""

    def __init__(self) -> None:
        table = None
        try:
            table = json.loads(cache_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.table = table or _bundled()
        self.meta = self.table.get("_meta", {})
        self.overrides: list[dict] = []
        try:
            data = tomllib.loads(overrides_file().read_text("utf-8"))
            self.overrides = data.get("model", [])
        except (OSError, tomllib.TOMLDecodeError):
            pass

    def _override(self, keys: list[str], day: str | None) -> Rate | None:
        """Best dated override for the first matching key."""
        for key in keys:
            hits = [o for o in self.overrides
                    if str(o.get("id", "")).lower() == key]
            dated = [o for o in hits if not day or
                     str(o.get("effective_from", "0000")) <= day]
            if dated:
                o = max(dated, key=lambda x: str(x.get("effective_from", "")))
                return Rate(
                    key, o.get("provider", "unknown"), o.get("input"),
                    o.get("output"), o.get("cache_write"),
                    o.get("cache_read"), o.get("source", "user override"),
                    effective_from=o.get("effective_from"),
                    basis="dated_override")
        return None

    def lookup(self, model: str | None, day: str | None = None
               ) -> Rate | None:
        """Find a rate for `model` on `day` (YYYY-MM-DD) or None."""
        if not model:
            return None
        keys = normalize(model)
        hit = self._override(keys, day)
        if hit:
            return hit
        models = self.table.get("models", {})
        for key in keys:
            r = models.get(key)
            if r:
                return Rate(
                    key, r["provider"], r["input"], r["output"],
                    r.get("cache_write"), r.get("cache_read"),
                    self.meta.get("source", "bundled snapshot"),
                    fetched_at=self.meta.get("fetched_at"),
                    tiered=bool(r.get("tiered")))
        return None
