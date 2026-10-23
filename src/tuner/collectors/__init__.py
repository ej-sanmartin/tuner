"""Agent usage collectors (adapter architecture)."""

from __future__ import annotations

from tuner.collectors.base import SourceFile, UsageCollector
from tuner.collectors.claude import ClaudeCollector
from tuner.collectors.cursor import CursorCollector


def build_collectors(cfg) -> list[UsageCollector]:
    """Instantiate enabled collectors from configuration."""
    out: list[UsageCollector] = []
    redact = cfg.privacy.redact_patterns
    if cfg.sources.claude_code:
        out.append(ClaudeCollector(cfg.sources.extra_claude_dirs, redact))
    if cfg.sources.cursor:
        out.append(CursorCollector(cfg.sources.cursor_state_db, redact))
    return out


__all__ = ["SourceFile", "UsageCollector", "build_collectors",
           "ClaudeCollector", "CursorCollector"]
