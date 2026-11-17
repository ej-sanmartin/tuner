"""OpenCode, Open WebUI, and Hermes collectors."""

import sqlite3
from pathlib import Path

from tuner import config
from tuner.collectors import build_collectors
from tuner.collectors.hermes import HermesCollector
from tuner.collectors.open_webui import OpenWebUICollector
from tuner.collectors.opencode import OpenCodeCollector
from tuner.commands import doctor


def _db(path, script):
    """Create a SQLite file from a script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(script)
    conn.commit()
    conn.close()


def _parse(col):
    """Parse the one source the collector finds."""
    sources = list(col.iter_sources())
    assert len(sources) == 1
    return col.parse(sources[0])


def test_opencode_uses_messages_not_rollup(env):
    """Message tokens are kept; the session rollup is not added again."""
    path = env / ".local/share/opencode/opencode.db"
    _db(path, """
        CREATE TABLE session_v2 (
          id TEXT, directory TEXT, title TEXT, parent_id TEXT,
          time_created INT, time_updated INT, tokens_input INT,
          tokens_output INT, tokens_reasoning INT, tokens_cache_read INT,
          tokens_cache_write INT);
        CREATE TABLE session_message (
          id TEXT, session_id TEXT, type TEXT, seq INT,
          time_created INT, data TEXT);
        INSERT INTO session_v2 VALUES (
          's1', '/work/demo', 'title', NULL, 1794727193640, 1794728120264,
          100, 9999, 0, 5, 0);
        INSERT INTO session_message VALUES
          ('u', 's1', 'user', 0, 1794727193640,
           '{"text":"token=sk-abcdefghijklmnopqrstuvwxyz"}'),
          ('a', 's1', 'assistant', 1, 1794727200000,
           '{"model":{"id":"qwen3.5:4b"},"tokens":{"input":40,"output":10,
             "reasoning":2,"cache":{"read":5,"write":1}}}');
    """)
    parsed = _parse(OpenCodeCollector())
    assert parsed.sessions[0].repo == "demo"
    assert "[REDACTED]" in parsed.turns[0].prompt_preview
    usage = parsed.usage
    assert len(usage) == 1
    assert usage[0].input_tokens == 40
    assert usage[0].output_tokens == 12  # 10 + reasoning
    assert usage[0].cache_read_tokens == 5
    assert usage[0].turn_id == parsed.turns[0].id
    assert usage[0].model == "qwen3.5:4b"
    assert any("rollup" in err for err in parsed.errors)


def test_wal_changes_fingerprint(env):
    """A WAL write changes the source fingerprint."""
    path = env / ".local/share/opencode/opencode.db"
    _db(path, "CREATE TABLE session_v2 (id TEXT);")
    col = OpenCodeCollector()
    first = next(col.iter_sources()).fingerprint
    Path(f"{path}-wal").write_bytes(b"x" * 8)
    assert next(col.iter_sources()).fingerprint != first


def test_webui_links_usage_to_parent_turn(env):
    """Assistant usage hangs off the parent user message."""
    path = env / ".open-webui/webui.db"
    _db(path, """
        CREATE TABLE chat (
          id TEXT, title TEXT, created_at INT, updated_at INT);
        CREATE TABLE chat_message (
          id TEXT, chat_id TEXT, role TEXT, parent_id TEXT, content TEXT,
          model_id TEXT, usage TEXT, created_at INT, error TEXT);
        INSERT INTO chat VALUES ('c', 'lora', 1794793508, 1794793600);
        INSERT INTO chat_message VALUES
          ('u', 'c', 'user', NULL, 'explain lora', NULL, NULL,
           1794793508, NULL),
          ('a', 'c', 'assistant', 'u', 'answer', 'qwen3.5:4b',
           '{"input_tokens":10,"output_tokens":4}', 1794793510, NULL);
    """)
    parsed = _parse(OpenWebUICollector())
    assert parsed.turns[0].prompt_preview == "explain lora"
    assert parsed.usage[0].input_tokens == 10
    assert parsed.usage[0].output_tokens == 4
    assert parsed.usage[0].turn_id == parsed.turns[0].id
    assert parsed.usage[0].measurement == "measured"


def test_hermes_model_usage_not_duplicated(env):
    """session_model_usage wins over per-message token_count."""
    path = env / ".hermes/state.db"
    _db(path, """
        CREATE TABLE sessions (
          id TEXT, title TEXT, cwd TEXT, parent_session_id TEXT,
          model TEXT, started_at TEXT, ended_at TEXT,
          input_tokens INT, output_tokens INT, cache_read_tokens INT,
          cache_write_tokens INT, reasoning_tokens INT);
        CREATE TABLE messages (
          id TEXT, session_id TEXT, role TEXT, content TEXT,
          timestamp TEXT, token_count INT, tool_name TEXT,
          tool_calls TEXT);
        CREATE TABLE session_model_usage (
          session_id TEXT, model TEXT, input_tokens INT,
          output_tokens INT, cache_read_tokens INT,
          cache_write_tokens INT, reasoning_tokens INT);
        INSERT INTO sessions VALUES (
          'h1', 'chat', '/work/demo', NULL, 'grok',
          '2026-11-12T00:00:00Z', '2026-11-12T00:05:00Z',
          5, 5, 0, 0, 0);
        INSERT INTO messages VALUES
          ('m1', 'h1', 'user', 'hello', '2026-11-12T00:00:00Z', 9,
           NULL, NULL),
          ('m2', 'h1', 'assistant', 'hi', '2026-11-12T00:01:00Z', 8,
           NULL, NULL);
        INSERT INTO session_model_usage VALUES
          ('h1', 'grok', 3, 4, 1, 2, 6);
    """)
    parsed = _parse(HermesCollector())
    assert len(parsed.usage) == 1
    assert parsed.usage[0].input_tokens == 3
    assert parsed.usage[0].output_tokens == 10  # 4 + reasoning 6
    assert parsed.usage[0].cache_write_tokens == 2
    assert parsed.usage[0].turn_id == parsed.turns[0].id
    assert parsed.turns[0].prompt_preview == "hello"


def test_missing_optional_sources_stay_quiet(env, conn):
    """Absent OpenCode, Open WebUI, and Hermes are not doctor warnings."""
    conn.close()
    names = {item["name"] for item in doctor.checks()}
    assert "source: opencode" not in names
    assert "source: open_webui" not in names
    assert "source: hermes" not in names


def test_flags_disable_collectors(env):
    """Each new source can be turned off."""
    cfg = config.load()
    cfg.values["sources"]["opencode"] = False
    cfg.values["sources"]["hermes"] = False
    names = [c.name for c in build_collectors(cfg)]
    assert "opencode" not in names and "hermes" not in names
    assert "open_webui" in names
