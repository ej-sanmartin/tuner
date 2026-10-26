"""Cursor collector: global discovery of agent transcripts, enriched with
hook events and (optionally) Cursor's internal state DB."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from tuner import hook_spool
from tuner.collectors import cursor_paths as cp
from tuner.collectors.base import PARSER_VERSION, SourceFile
from tuner.collectors.common import iso_utc, repo_for
from tuner.collectors.cursor_enrich import (
    apply_bubbles,
    apply_hooks,
    dominant_model,
)
from tuner.collectors.cursor_estimate import KNOWN_GAPS, estimate_usage
from tuner.collectors.cursor_parser import read_transcript
from tuner.collectors.cursor_state import Composer, CursorState
from tuner.collectors.cursor_tracking import load_tracking
from tuner.models import EventRec, ParsedSource, SessionRec
from tuner.security.redact import compile_extra

AGENT = "cursor"


def layout(path: Path, root: Path) -> tuple[str, str, str | None]:
    """Return (slug, native_id, parent_id) from a transcript path."""
    rel = path.relative_to(root).parts
    slug = rel[0]
    if "subagents" in rel:
        return slug, path.stem, rel[rel.index("subagents") - 1]
    return slug, path.stem, None


def spawn_turns(comp: Composer) -> dict[str, int]:
    """Map each tool-call id to the index of the user turn containing it."""
    out: dict[str, int] = {}
    turn = -1
    for b in comp.bubbles:
        if b.kind == 1:
            turn += 1
        elif b.tool_call_id and turn >= 0:
            out[b.tool_call_id] = turn
    return out


class CursorCollector:
    """Collector for Cursor agent sessions (main agents and subagents)."""

    name = AGENT

    def __init__(self, use_state_db: bool = True,
                 redact_patterns: list[str] | None = None) -> None:
        self.use_state_db = use_state_db
        self.extra = compile_extra(redact_patterns or [])
        self._hooks: hook_spool.HookIndex | None = None
        self._state: CursorState | None = None
        self._tracking: tuple[dict, dict] | None = None

    # -- lazy helpers ----------------------------------------------------
    @property
    def hooks(self) -> hook_spool.HookIndex:
        """Hook event index (loaded once per run)."""
        if self._hooks is None:
            self._hooks = hook_spool.HookIndex()
        return self._hooks

    @property
    def state(self) -> CursorState | None:
        """State DB handle, or None when disabled."""
        if not self.use_state_db:
            return None
        if self._state is None:
            self._state = CursorState(cp.state_db_path())
        return self._state

    @property
    def tracking(self) -> tuple[dict[str, str], dict[str, str]]:
        """(models, titles) from the AI tracking DB."""
        if self._tracking is None:
            self._tracking = load_tracking(cp.tracking_db_path())
        return self._tracking

    def close(self) -> None:
        """Release the state DB handle."""
        if self._state is not None:
            self._state.close()

    # -- collector interface ---------------------------------------------
    def discover(self) -> bool:
        """True if any workspace has agent transcripts."""
        return any(cp.projects_dir().glob("*/agent-transcripts"))

    def locations(self) -> list[Path]:
        """Directories/files read by this collector."""
        locs = [cp.projects_dir()]
        for extra in (cp.state_db_path(), cp.tracking_db_path(),
                      hook_spool.spool_file()):
            if extra.exists():
                locs.append(extra)
        return locs

    def iter_sources(self, since: datetime | None = None
                     ) -> Iterator[SourceFile]:
        """Yield main and subagent transcripts across all workspaces."""
        cutoff = since.timestamp() if since else None
        root = cp.projects_dir()
        for path in root.glob("*/agent-transcripts/**/*.jsonl"):
            try:
                st = path.stat()
            except OSError:
                continue
            if cutoff is not None and st.st_mtime < cutoff:
                continue
            _, native, _ = layout(path, root)
            salt = f"{PARSER_VERSION}:{self.hooks.count(native)}"
            yield SourceFile(path, AGENT, st.st_size, st.st_mtime_ns, salt)

    def capabilities(self) -> dict:
        """Field-level measurement status for `tuner doctor`."""
        state = self.state
        return {
            "agent": AGENT,
            "tokens": {k: "estimated" for k in
                       ("input", "output", "cache_write", "cache_read")}
            | {"cache_write": "unavailable"},
            "model": "measured (state db / hooks) or unavailable",
            "timestamps": "measured via state db or hooks; else file mtime",
            "tool_calls": "measured (names/targets); failures partial",
            "subagents": "measured via transcript layout",
            "compaction": "measured via preCompact hook only",
            "state_db": ("available" if state and state.available
                         else "unavailable: "
                         f"{state.error if state else 'off'}"),
            "hooks_events": len(self.hooks.by_conv),
            "known_gaps": KNOWN_GAPS,
            "notes": ["Cursor exposes no token counts locally; usage is "
                      "estimated (see cursor_estimate.py)"],
        }

    # -- parsing ---------------------------------------------------------
    def parse(self, src: SourceFile) -> ParsedSource:
        """Parse one transcript into sessions/turns/tools/usage/events."""
        out = ParsedSource()
        root = cp.projects_dir()
        slug, native, parent = layout(src.path, root)
        sid = f"{AGENT}:{native}"
        try:
            drafts, bad = read_transcript(src.path, sid, self.extra)
        except OSError as exc:
            out.errors.append(f"cannot read transcript: {exc}")
            return out
        if bad:
            out.errors.append(f"{bad} malformed JSONL line(s) skipped")
        hook_events = self.hooks.events(native)
        workspace = next((r["workspace_roots"][0] for r in hook_events
                          if r.get("workspace_roots")), None)
        path_str = workspace or cp.decode_slug(slug)
        root_path, repo = repo_for(path_str)
        models, titles = self.tracking
        model = models.get(native) or next(
            (r["model"] for r in reversed(hook_events) if r.get("model")),
            None)
        time_quality = "file_mtime"
        comp = self.state.composer(native) if self.state else None
        if comp is not None:
            err = apply_bubbles(drafts, comp)
            model = comp.model or model
            if err:
                out.errors.append(err)
            if any(d.method == "cursor_bubbles_v2" for d in drafts):
                time_quality = "measured"
        elif (self.state is not None and self.state.error
              and "not found" not in self.state.error):
            out.errors.append(self.state.error)
        if time_quality != "measured" and apply_hooks(drafts, hook_events):
            time_quality = "hook"
        model = dominant_model(drafts, model)
        sess = self._session(src, sid, native, parent, slug, root_path,
                             repo, titles.get(native), drafts, time_quality)
        out.sessions.append(sess)
        for d in drafts:
            out.turns.append(d.rec)
            out.tools.extend(d.tools)
        compactions = [t for e in hook_events if e["event"] == "preCompact"
                       if (t := iso_utc(e["ts"]))]
        out.usage = estimate_usage(drafts, sid, model, str(src.path),
                                   "cursor_local_transcript", compactions)
        if comp is not None:
            out.events += self._spawn_events(sid, comp, drafts)
        out.events += self._hook_events(sid, hook_events, drafts)
        if model is None:
            out.errors.append("model unknown for this conversation")
        return out

    def _session(self, src, sid, native, parent, slug, root_path, repo,
                 title, drafts, time_quality) -> SessionRec:
        """Build the session record with best-available timestamps."""
        starts = [d.rec.started_at for d in drafts if d.rec.started_at]
        ends = [d.rec.ended_at for d in drafts if d.rec.ended_at]
        try:
            st = src.path.stat()
            mtime = iso_utc(st.st_mtime)
            born = iso_utc(getattr(st, "st_birthtime", None))
        except OSError:
            mtime = born = None
        return SessionRec(
            id=sid, agent=AGENT, native_id=native,
            kind="subagent" if parent else "main",
            parent_id=f"{AGENT}:{parent}" if parent else None,
            agent_ref=native if parent else None,
            project_path=root_path, repo=repo or slug, title=title,
            started_at=min(starts) if starts else born,
            ended_at=max(ends) if ends else mtime,
            time_quality=time_quality, source_path=str(src.path),
            meta={"slug": slug, "path_decoded": root_path is not None})

    def _spawn_events(self, sid, comp, drafts) -> list[EventRec]:
        """Link subagents to the parent turn that launched them."""
        events: list[EventRec] = []
        by_call = spawn_turns(comp)
        for child in comp.subagent_ids:
            cc = self.state.composer(child) if self.state else None
            call = next((b.spawn_tool_call_id for b in cc.bubbles
                         if b.spawn_tool_call_id), None) if cc else None
            idx = by_call.get(call) if call else None
            turn = drafts[idx].rec.id if idx is not None and \
                idx < len(drafts) else None
            events.append(EventRec(
                id=f"{AGENT}:spawn:{child}", session_id=sid, turn_id=turn,
                ts=None, kind="subagent_spawn",
                data={"agent_ref": child, "link": "state_db"
                      if turn else "unlinked"}))
        return events

    def _hook_events(self, sid, hook_events, drafts) -> list[EventRec]:
        """Compaction (measured context size) and subagent stops."""
        events: list[EventRec] = []
        starts = [(d.rec.started_at, d.rec.id) for d in drafts]
        for ev in hook_events:
            if ev["event"] != "preCompact":
                continue
            ts = iso_utc(ev["ts"])
            turn = None
            for started, tid in starts:
                if started and ts and started <= ts:
                    turn = tid
            events.append(EventRec(
                id=f"{AGENT}:compact:{sid}:{ev['ts']}", session_id=sid,
                turn_id=turn, ts=ts, kind="compaction",
                data={k: ev.get(k) for k in (
                    "trigger", "context_tokens", "context_window_size",
                    "message_count")} | {"measurement": "measured"}))
        return events

