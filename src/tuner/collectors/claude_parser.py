"""Parser for Claude Code JSONL transcripts.

Accounting rules (learned from real transcripts and upstream tools):
* One API response is written as several `assistant` lines sharing
  `requestId`/`message.id`; only the last carries the final
  `output_tokens`. We keep one usage record per request (max output).
* Resumed sessions replay earlier entries; we skip repeated `uuid`s and
  rely on primary keys across files.
* Subagent work (`isSidechain`) gets its own child session, never counted
  in the parent turn directly. The Task tool's reported `totalTokens` is
  stored only as a reconciliation hint, never added to totals.
"""

from __future__ import annotations

import json
from pathlib import Path

from tuner.collectors.claude_text import (
    ARGS,
    CMD,
    META_PREFIXES,
    result_text,
    text_of,
)
from tuner.collectors.common import (
    iso_utc,
    repo_for,
    tool_target,
)
from tuner.models import (
    MEASURED,
    EventRec,
    ParsedSource,
    SessionRec,
    ToolCallRec,
    TurnRec,
    UsageRec,
)
from tuner.security.redact import preview

AGENT = "claude_code"
SPAWN_TOOLS = {"Task", "Agent"}
class ClaudeFileParser:
    """Stateful, single-pass parser for one transcript file."""

    def __init__(self, path: Path, projects_root: Path, extra=()) -> None:
        self.path, self.extra = path, extra
        rel = path.relative_to(projects_root).parts
        self.is_sub_file = "subagents" in rel
        self.slug = rel[0]
        self.file_agent = (path.stem.removeprefix("agent-")
                           if self.is_sub_file else None)
        self.file_sid = (rel[rel.index("subagents") - 1]
                         if self.is_sub_file else path.stem)
        self.out = ParsedSource()
        self.sessions: dict[str, SessionRec] = {}
        self.calls: dict[str, UsageRec] = {}
        self.tools: dict[str, ToolCallRec] = {}
        self.seen: set[str] = set()
        self.turn: TurnRec | None = None
        self.turns_by_id: dict[str, TurnRec] = {}
        self.bad_lines = 0
        self.seq: dict[str, int] = {}
        self.last_stop: dict[str, str | None] = {}
        self.pending_spawn: dict[str, tuple[str | None, int]] = {}

    # -- session helpers -------------------------------------------------
    def _session(self, entry: dict) -> SessionRec:
        """Get/create the session (main or child) for an entry."""
        sid = str(entry.get("sessionId") or self.file_sid)
        agent_ref = None
        if entry.get("isSidechain") or self.is_sub_file:
            agent_ref = str(entry.get("agentId") or self.file_agent
                            or "sidechain")
        key = f"{sid}:{agent_ref}" if agent_ref else sid
        sess = self.sessions.get(key)
        if sess is None:
            sess = SessionRec(
                id=f"{AGENT}:{key}", agent=AGENT, native_id=sid,
                kind="subagent" if agent_ref else "main",
                parent_id=f"{AGENT}:{sid}" if agent_ref else None,
                agent_ref=agent_ref, source_path=str(self.path))
            self.sessions[key] = sess
        cwd = entry.get("cwd")
        if cwd and not sess.project_path:
            root, name = repo_for(str(cwd))
            sess.project_path, sess.repo = root, name
            sess.meta["cwd"] = str(cwd)
        if entry.get("gitBranch"):
            sess.meta.setdefault("git_branch", entry["gitBranch"])
        if entry.get("version"):
            sess.meta.setdefault("client_version", entry["version"])
        ts = iso_utc(entry.get("timestamp"))
        if ts:
            sess.started_at = min(sess.started_at or ts, ts)
            sess.ended_at = max(sess.ended_at or ts, ts)
        return sess

    # -- entry handlers --------------------------------------------------
    def feed(self, line_no: int, entry: dict) -> None:
        """Process one decoded JSONL entry."""
        etype = entry.get("type")
        if etype == "summary":
            main = self.sessions.get(self.file_sid)
            if main and entry.get("summary"):
                main.title = preview(str(entry["summary"]), 120, self.extra)
            return
        if etype not in ("user", "assistant", "system"):
            return
        uuid = entry.get("uuid")
        if uuid:
            if uuid in self.seen:
                return
            self.seen.add(uuid)
        sess = self._session(entry)
        ts = iso_utc(entry.get("timestamp"))
        if etype == "system":
            self._system(sess, entry, ts, line_no)
        elif etype == "user":
            self._user(sess, entry, ts, line_no)
        else:
            self._assistant(sess, entry, ts, line_no)
        if self.turn and sess.kind == "main" and ts:
            self.turn.ended_at = ts

    def _system(self, sess, entry, ts, line_no) -> None:
        """Compaction boundaries are recorded as events."""
        if entry.get("subtype") != "compact_boundary":
            return
        meta = entry.get("compactMetadata") or {}
        self.out.events.append(EventRec(
            id=f"{AGENT}:evt:{entry.get('uuid') or line_no}",
            session_id=sess.id, turn_id=self._turn_id(sess), ts=ts,
            kind="compaction", source_line=line_no,
            data={"trigger": meta.get("trigger"),
                  "pre_tokens": meta.get("preTokens")}))

    def _turn_id(self, sess: SessionRec) -> str | None:
        """Current main-thread turn id (None for subagent sessions)."""
        return self.turn.id if self.turn and sess.kind == "main" else None

    def _user(self, sess, entry, ts, line_no) -> None:
        """Start turns on human prompts; attach tool results otherwise."""
        msg = entry.get("message") or {}
        content = msg.get("content")
        text, has_result = text_of(content)
        if has_result:
            self._tool_results(sess, content, entry, line_no)
            return
        if sess.kind == "subagent" or entry.get("isSidechain"):
            return
        if entry.get("isCompactSummary"):
            return
        if entry.get("isMeta") or text.startswith(META_PREFIXES):
            return
        if text.startswith("[Request interrupted by user"):
            if self.turn:
                self.turn.outcome = "interrupted"
            return
        cmd = CMD.search(text)
        if cmd:
            args = ARGS.search(text)
            text = f"{cmd.group(1)} {args.group(1) if args else ''}".strip()
        if not text.strip():
            return
        seq = self.seq.get(sess.id, 0)
        self.seq[sess.id] = seq + 1
        turn = TurnRec(
            id=f"{AGENT}:turn:{entry.get('uuid') or line_no}",
            session_id=sess.id, seq=seq, started_at=ts, ended_at=ts,
            prompt_preview=preview(text, 240, self.extra),
            prompt_chars=len(text), outcome="incomplete",
            source_line=line_no)
        self.out.turns.append(turn)
        self.turns_by_id[turn.id] = turn
        self.turn = turn

    def _tool_results(self, sess, content, entry, line_no) -> None:
        """Mark tool failures and link Task results to subagent ids."""
        for block in content:
            if not (isinstance(block, dict)
                    and block.get("type") == "tool_result"):
                continue
            call = self.tools.get(str(block.get("tool_use_id")))
            if call is not None:
                failed = bool(block.get("is_error"))
                call.is_error = failed
                if failed:
                    call.error_preview = preview(result_text(block), 160,
                                                 self.extra)
        res = entry.get("toolUseResult")
        if isinstance(res, dict) and res.get("agentId"):
            tids = [str(b.get("tool_use_id")) for b in content
                    if isinstance(b, dict)
                    and b.get("type") == "tool_result"]
            tid = next((t for t in tids if t in self.pending_spawn), tids[0])
            turn_id, ln = self.pending_spawn.pop(tid, (None, line_no))
            self.out.events.append(EventRec(
                id=f"{AGENT}:spawn:{res['agentId']}", session_id=sess.id,
                turn_id=turn_id, ts=iso_utc(entry.get("timestamp")),
                kind="subagent_spawn", source_line=ln,
                data={"agent_ref": str(res["agentId"]),
                      "tool_use_id": tid,
                      "reported_total_tokens": res.get("totalTokens"),
                      "reported_tool_uses": res.get("totalToolUseCount")}))

    def _assistant(self, sess, entry, ts, line_no) -> None:
        """Record usage (one per request) and tool calls."""
        msg = entry.get("message") or {}
        turn_id = self._turn_id(sess)
        model = msg.get("model")
        if entry.get("isApiErrorMessage") and self.turn:
            self.turn.outcome = "error"
        usage = msg.get("usage")
        if isinstance(usage, dict) and model != "<synthetic>":
            self._usage(sess, entry, msg, usage, model, ts, line_no, turn_id)
        stop = msg.get("stop_reason")
        if stop and self.turn and sess.kind == "main":
            self.last_stop[self.turn.id] = stop
        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                self._tool_use(sess, block, ts, line_no, turn_id)

    def _usage(self, sess, entry, msg, usage, model, ts, line_no,
               turn_id) -> None:
        """Keep the record with the largest output per request."""
        key = str(entry.get("requestId") or msg.get("id") or
                  entry.get("uuid") or line_no)
        rec = UsageRec(
            id=f"{AGENT}:{key}", session_id=sess.id, turn_id=turn_id, ts=ts,
            model=model,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cache_write_tokens=int(
                usage.get("cache_creation_input_tokens") or 0),
            cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
            measurement=MEASURED, confidence="high",
            source="claude_code_transcript", source_line=line_no)
        old = self.calls.get(rec.id)
        if old is None or rec.output_tokens >= old.output_tokens:
            self.calls[rec.id] = rec

    def _tool_use(self, sess, block, ts, line_no, turn_id) -> None:
        """Record a tool invocation; remember Task spawns for linking."""
        tid = str(block.get("id") or f"{line_no}:{block.get('name')}")
        if tid in self.tools:
            return
        name = str(block.get("name") or "unknown")
        call = ToolCallRec(
            id=f"{AGENT}:tool:{tid}", session_id=sess.id, turn_id=turn_id,
            ts=ts, name=name, target=tool_target(block.get("input")),
            source_line=line_no)
        self.tools[tid] = call
        if name in SPAWN_TOOLS and turn_id:
            self.pending_spawn[tid] = (turn_id, line_no)

    # -- finish ----------------------------------------------------------
    def finish(self) -> ParsedSource:
        """Assemble final records and compute turn outcomes."""
        for turn in self.out.turns:
            if turn.outcome == "incomplete" and \
                    self.last_stop.get(turn.id) == "end_turn":
                turn.outcome = "completed"
        self.out.sessions = list(self.sessions.values())
        self.out.usage = list(self.calls.values())
        self.out.tools = list(self.tools.values())
        if self.bad_lines:
            self.out.errors.append(
                f"{self.bad_lines} malformed JSONL line(s) skipped")
        return self.out


def parse_claude_file(path: Path, projects_root: Path,
                      extra=()) -> ParsedSource:
    """Parse one transcript (streaming) into normalized records."""
    parser = ClaudeFileParser(path, projects_root, extra)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    parser.bad_lines += 1
                    continue
                if isinstance(entry, dict):
                    parser.feed(line_no, entry)
    except OSError as exc:
        parser.out.errors.append(f"cannot read file: {exc}")
    return parser.finish()
