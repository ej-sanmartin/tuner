"""Synthetic, realistic transcript builders (no personal data)."""

from __future__ import annotations

import json
from pathlib import Path

SID = "11111111-aaaa-bbbb-cccc-000000000001"
CWD = "/work/demo-repo"


def _w(path: Path, lines: list) -> Path:
    """Write JSONL (strings are written verbatim, e.g. malformed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = [ln if isinstance(ln, str) else json.dumps(ln) for ln in lines]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def usage(i=1, o=1, cw=0, cr=0) -> dict:
    """Claude usage block."""
    return {"input_tokens": i, "output_tokens": o,
            "cache_creation_input_tokens": cw,
            "cache_read_input_tokens": cr}


def entry(kind, uuid, ts, content, **kw) -> dict:
    """Generic Claude transcript entry."""
    base = {"type": kind, "uuid": uuid, "sessionId": kw.pop("sid", SID),
            "timestamp": ts, "cwd": CWD, "version": "2.0.0"}
    msg = {"role": kind if kind != "system" else "system",
           "content": content}
    msg.update(kw.pop("msg", {}))
    base["message"] = msg
    base.update(kw)
    return base


def tool_use(tid, name, **inp) -> dict:
    """tool_use content block."""
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def tool_result(tid, text="ok", error=False) -> dict:
    """tool_result content block."""
    return {"type": "tool_result", "tool_use_id": tid, "content": text,
            "is_error": error}


def build_claude(home: Path) -> dict[str, Path]:
    """Create a ~/.claude tree with a main session and a subagent file."""
    proj = home / ".claude" / "projects" / "-work-demo-repo"
    ts = "2026-10-12T10:00:%02dZ"
    main = [
        entry("user", "u1", ts % 0, "Fix the failing parser test"),
        # One API response streamed over two lines: output is cumulative.
        entry("assistant", "a1", ts % 1, [{"type": "text", "text": "Looking"}],
              requestId="req1", msg={"id": "m1", "model": "claude-sonnet-4-5",
                                     "usage": usage(10, 5, 100, 1000)}),
        entry("assistant", "a2", ts % 2,
              [tool_use("t1", "Read", file_path="/work/demo-repo/p.py")],
              requestId="req1", msg={"id": "m1", "model": "claude-sonnet-4-5",
                                     "usage": usage(10, 60, 100, 1000)}),
        entry("user", "u2", ts % 3, [tool_result("t1")]),
        entry("assistant", "a3", ts % 4,
              [tool_use("t2", "Task", description="explore", prompt="x")],
              requestId="req2", msg={"id": "m2", "model": "claude-sonnet-4-5",
                                     "usage": usage(5, 40, 0, 1200)}),
        entry("user", "u3", ts % 5, [tool_result("t2", "done")],
              toolUseResult={"agentId": "abc", "totalTokens": 999}),
        entry("assistant", "a4", ts % 6,
              [tool_use("t3", "Bash", command="pytest -x")],
              requestId="req3", msg={"id": "m3", "model": "claude-sonnet-4-5",
                                     "usage": usage(5, 30, 0, 1300)}),
        entry("user", "u4", ts % 7, [tool_result("t3", "boom", True)]),
        {"type": "system", "subtype": "compact_boundary", "uuid": "s1",
         "sessionId": SID, "timestamp": ts % 8, "cwd": CWD,
         "compactMetadata": {"trigger": "auto", "preTokens": 150000}},
        entry("assistant", "a5", ts % 9, [{"type": "text", "text": "Fixed"}],
              requestId="req4", msg={"id": "m4", "model": "claude-sonnet-4-5",
                                     "stop_reason": "end_turn",
                                     "usage": usage(5, 20, 0, 1400)}),
        entry("assistant", "a2", ts % 2, [], requestId="req1"),  # replay
        "{not valid json",
        entry("user", "u5", "2026-10-12T10:05:00Z", "yes"),
        entry("assistant", "a6", "2026-10-12T10:05:05Z",
              [{"type": "text", "text": "ok"}], requestId="req5",
              msg={"id": "m5", "model": "claude-sonnet-4-5",
                   "stop_reason": "end_turn", "usage": usage(2, 8, 0, 1500)}),
        entry("user", "u6", "2026-10-12T18:00:00Z",
              "Now refactor the whole tokenizer module to be streaming"),
        entry("assistant", "a7", "2026-10-12T18:00:09Z",
              [{"type": "text", "text": "Sure"}], requestId="req6",
              msg={"id": "m6", "model": "<synthetic>", "usage": usage(0, 0)}),
    ]
    sub = [
        entry("user", "su1", ts % 20, "explore the repo", isSidechain=True,
              agentId="abc"),
        entry("assistant", "sa1", ts % 21, [{"type": "text", "text": "..."}],
              isSidechain=True, agentId="abc", requestId="reqS1",
              msg={"id": "mS1", "model": "claude-haiku-4-5",
                   "stop_reason": "end_turn", "usage": usage(7, 70, 0, 700)}),
    ]
    files = {
        "main": _w(proj / f"{SID}.jsonl", main),
        "sub": _w(proj / SID / "subagents" / "agent-abc.jsonl", sub),
    }
    return files


def build_cursor(home: Path, conv="22222222-aaaa-bbbb-cccc-000000000002"
                 ) -> dict[str, Path]:
    """Create a ~/.cursor/projects tree with a transcript + subagent."""
    base = home / ".cursor" / "projects" / "work-demo-repo" / \
        "agent-transcripts" / conv
    def user(text):
        return {"role": "user", "message": {"content": [
            {"type": "text", "text": f"<user_query>\n{text}\n</user_query>"}]}}

    def asst(text=None, tool=None, **inp):
        blocks = []
        if text:
            blocks.append({"type": "text", "text": text})
        if tool:
            blocks.append({"type": "tool_use", "name": tool, "input": inp})
        return {"role": "assistant", "message": {"content": blocks}}

    main = [
        user("Add a CLI flag for verbose output"),
        asst("I'll look at the CLI module.", "Read", path="/work/cli.py"),
        asst(None, "Read", path="/work/cli.py"),
        asst(None, "StrReplace", path="/work/cli.py", old_string="a",
             new_string="b"),
        asst("Done."),
        {"type": "turn_ended", "status": "success"},
        user("ok"),
        asst("Anything else?"),
        {"type": "turn_ended", "status": "success"},
    ]
    sub = [user("explore"), asst("explored")]
    return {
        "main": _w(base / f"{conv}.jsonl", main),
        "sub": _w(base / "subagents" / "child-0001.jsonl", sub),
    }
