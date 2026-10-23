"""Claude Code transcript parsing and accounting."""

from fixtures.builders import SID, build_claude

from tuner.collectors.claude import ClaudeCollector


def parse_all(env):
    files = build_claude(env)
    col = ClaudeCollector()
    assert col.discover()
    return files, {s.path.name: col.parse(s) for s in col.iter_sources()}


def test_streaming_updates_counted_once(env):
    _, parsed = parse_all(env)
    main = parsed[f"{SID}.jsonl"]
    by_id = {u.id: u for u in main.usage}
    req1 = by_id["claude_code:req1"]
    # two streamed lines -> one record with the final (max) output
    assert req1.output_tokens == 60
    assert req1.input_tokens == 10 and req1.cache_read_tokens == 1000
    assert len([u for u in main.usage if u.id.endswith("req1")]) == 1


def test_synthetic_model_and_malformed_lines(env):
    _, parsed = parse_all(env)
    main = parsed[f"{SID}.jsonl"]
    assert all(u.model != "<synthetic>" for u in main.usage)
    assert any("malformed" in e for e in main.errors)


def test_measured_quality_metadata(env):
    _, parsed = parse_all(env)
    u = parsed[f"{SID}.jsonl"].usage[0]
    assert (u.measurement, u.confidence, u.source) == (
        "measured", "high", "claude_code_transcript")


def test_turns_and_outcomes(env):
    _, parsed = parse_all(env)
    turns = parsed[f"{SID}.jsonl"].turns
    assert [t.seq for t in turns] == [0, 1, 2]
    assert turns[0].outcome == "completed"
    assert turns[0].prompt_preview.startswith("Fix the failing")


def test_tool_failures_and_targets(env):
    _, parsed = parse_all(env)
    tools = {t.name: t for t in parsed[f"{SID}.jsonl"].tools}
    assert tools["Bash"].is_error is True
    assert tools["Read"].is_error is False
    assert tools["Read"].target == "/work/demo-repo/p.py"


def test_compaction_and_subagent_events(env):
    _, parsed = parse_all(env)
    kinds = {e.kind: e for e in parsed[f"{SID}.jsonl"].events}
    assert kinds["compaction"].data["pre_tokens"] == 150000
    spawn = kinds["subagent_spawn"]
    assert spawn.data["agent_ref"] == "abc"
    assert spawn.turn_id is not None
    # Task's self-reported totalTokens is a hint only, never added
    assert spawn.data["reported_total_tokens"] == 999


def test_subagent_file_gets_child_session(env):
    _, parsed = parse_all(env)
    sub = parsed["agent-abc.jsonl"]
    sess = sub.sessions[0]
    assert sess.kind == "subagent" and sess.parent_id == f"claude_code:{SID}"
    assert sess.agent_ref == "abc"
    assert sub.usage[0].turn_id is None  # attributed via the parent turn
    assert not sub.turns


def test_session_repo_and_time(env):
    _, parsed = parse_all(env)
    sess = parsed[f"{SID}.jsonl"].sessions[0]
    assert sess.repo == "demo-repo"
    assert sess.started_at.startswith("2026-10-12T10:00:00")
