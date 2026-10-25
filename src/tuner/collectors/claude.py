"""Claude Code collector: discovery across platforms + transcript parsing."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from tuner import paths
from tuner.collectors.base import PARSER_VERSION, SourceFile
from tuner.collectors.claude_parser import AGENT, parse_claude_file
from tuner.models import ParsedSource
from tuner.security.redact import compile_extra


def wsl_homes() -> list[Path]:
    """Best-effort list of WSL home directories reachable from Windows."""
    homes: list[Path] = []
    if sys.platform != "win32":
        return homes
    for root in (r"\\wsl.localhost", r"\\wsl$"):
        try:
            distros = [d for d in Path(root).iterdir() if d.is_dir()]
        except OSError:
            continue
        for distro in distros:
            try:
                homes += [h for h in (distro / "home").iterdir()
                          if h.is_dir()]
            except OSError:
                continue
        if homes:
            break
    return homes


def claude_config_dirs(extra: list[str] | None = None) -> list[Path]:
    """Candidate Claude config roots (each may hold `projects/`)."""
    cands: list[Path] = []
    env = os.environ.get("CLAUDE_CONFIG_DIR", "")
    cands += [Path(p.strip()) for p in env.split(",") if p.strip()]
    home = paths.user_home()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    cands += [Path(xdg) / "claude"] if xdg else []
    cands += [home / ".config" / "claude", home / ".claude"]
    cands += [Path(p) for p in extra or []]
    cands += [h / ".claude" for h in wsl_homes()]
    seen, out = set(), []
    for c in cands:
        key = os.path.normcase(str(c))
        if key in seen:
            continue
        seen.add(key)
        try:
            if (c / "projects").is_dir():
                out.append(c)
        except OSError:
            continue
    return out


class ClaudeCollector:
    """Reads `<config>/projects/**/*.jsonl` transcripts."""

    name = AGENT

    def __init__(self, extra_dirs: list[str] | None = None,
                 redact_patterns: list[str] | None = None) -> None:
        self.extra_dirs = extra_dirs or []
        self.extra = compile_extra(redact_patterns or [])
        self._roots: dict[str, Path] = {}

    def discover(self) -> bool:
        """True if any Claude Code projects directory exists."""
        return bool(self.locations())

    def locations(self) -> list[Path]:
        """Existing `projects` directories that will be scanned."""
        return [c / "projects" for c in claude_config_dirs(self.extra_dirs)]

    def iter_sources(self, since: datetime | None = None
                     ) -> Iterator[SourceFile]:
        """Yield every transcript file (main + subagent)."""
        cutoff = since.timestamp() if since else None
        for root in self.locations():
            for path in root.rglob("*.jsonl"):
                try:
                    st = path.stat()
                except OSError:
                    continue  # locked / vanished; picked up next run
                if cutoff is not None and st.st_mtime < cutoff:
                    continue
                self._roots[str(path)] = root
                yield SourceFile(path, self.name, st.st_size, st.st_mtime_ns,
                                 PARSER_VERSION)

    def parse(self, src: SourceFile) -> ParsedSource:
        """Parse one transcript file."""
        root = self._roots.get(str(src.path)) or next(
            (r for r in self.locations() if r in src.path.parents), None)
        if root is None:
            out = ParsedSource()
            out.errors.append("file is outside any known projects dir")
            return out
        return parse_claude_file(src.path, root, self.extra)

    def capabilities(self) -> dict:
        """Field-level measurement status."""
        return {
            "agent": self.name,
            "tokens": {"input": "measured", "output": "measured",
                       "cache_write": "measured", "cache_read": "measured"},
            "model": "measured", "timestamps": "measured",
            "tool_calls": "measured", "tool_failures": "measured",
            "subagents": "measured", "compaction": "measured",
            "outcome": "inferred",
            "notes": ["cache_write uses total cache_creation tokens; the "
                      "1h-vs-5m split is not tracked"],
        }
