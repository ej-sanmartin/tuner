"""Collector interface shared by every agent adapter.

Adding a new agent means implementing `UsageCollector` and registering it
in `collectors/__init__.py`; the core pipeline never changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from tuner.models import ParsedSource


@dataclass(frozen=True)
class SourceFile:
    """A raw file a collector can parse, with its change fingerprint."""

    path: Path
    agent: str
    size: int
    mtime_ns: int
    salt: str = ""  # extra change signal (e.g. hook event count)

    @property
    def fingerprint(self) -> str:
        """Cheap change detector: size, mtime, and collector salt."""
        return f"{self.size}:{self.mtime_ns}:{self.salt}"


PARSER_VERSION = "2"  # bump to force a re-parse of every source


class UsageCollector(Protocol):
    """Discover, parse, and describe one agent's local records."""

    name: str

    def discover(self) -> bool:
        """True if this agent's local data exists on this machine."""
        ...

    def locations(self) -> list[Path]:
        """Directories/files this collector reads (for `tuner doctor`)."""
        ...

    def iter_sources(self, since: datetime | None = None
                     ) -> Iterator[SourceFile]:
        """Yield candidate source files (optionally modified >= since)."""
        ...

    def parse(self, src: SourceFile) -> ParsedSource:
        """Parse one file into normalized records (never raises on
        malformed content; reports problems in `ParsedSource.errors`)."""
        ...

    def capabilities(self) -> dict:
        """Which fields are measured vs estimated vs unavailable."""
        ...
