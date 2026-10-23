"""Normalized records shared by every collector and the storage layer.

Every record carries a `source_path` (+ line) so findings can always be
traced back to raw evidence. Token usage always carries quality metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MEASURED = "measured"
ESTIMATED = "estimated"
UNAVAILABLE = "unavailable"


@dataclass
class SessionRec:
    """One agent conversation (or one subagent run)."""

    id: str
    agent: str  # claude_code | cursor
    native_id: str
    kind: str = "main"  # main | subagent
    parent_id: str | None = None
    project_path: str | None = None
    repo: str | None = None
    title: str | None = None
    started_at: str | None = None  # ISO-8601 UTC
    ended_at: str | None = None
    time_quality: str = "measured"  # measured | hook | file_mtime
    agent_ref: str | None = None  # subagent id inside the parent
    source_path: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnRec:
    """One user prompt and the agent work that followed it."""

    id: str
    session_id: str
    seq: int
    started_at: str | None = None
    ended_at: str | None = None
    prompt_preview: str = ""  # redacted, truncated
    prompt_chars: int = 0
    outcome: str = "unknown"  # completed|interrupted|error|incomplete
    source_path: str = ""
    source_line: int = 0


@dataclass
class UsageRec:
    """Token usage for one model call, with quality metadata."""

    id: str
    session_id: str
    turn_id: str | None
    ts: str | None
    model: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    measurement: str = MEASURED
    confidence: str = "high"
    source: str = ""
    method: str | None = None
    source_path: str = ""
    source_line: int = 0

    @property
    def total(self) -> int:
        """All token categories summed (categories are disjoint)."""
        return (self.input_tokens + self.output_tokens
                + self.cache_write_tokens + self.cache_read_tokens)


@dataclass
class ToolCallRec:
    """One tool invocation, with failure status when observable."""

    id: str
    session_id: str
    turn_id: str | None
    ts: str | None
    name: str
    target: str = ""  # file path / command / pattern (redacted)
    is_error: bool | None = None  # None = unknown
    error_preview: str = ""
    source_path: str = ""
    source_line: int = 0


@dataclass
class EventRec:
    """A notable occurrence: compaction, subagent spawn, errors."""

    id: str
    session_id: str
    turn_id: str | None
    ts: str | None
    kind: str  # compaction | subagent_spawn | api_error | ...
    data: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""
    source_line: int = 0


@dataclass
class ParsedSource:
    """Everything extracted from one source file."""

    sessions: list[SessionRec] = field(default_factory=list)
    turns: list[TurnRec] = field(default_factory=list)
    usage: list[UsageRec] = field(default_factory=list)
    tools: list[ToolCallRec] = field(default_factory=list)
    events: list[EventRec] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # data-quality issues
