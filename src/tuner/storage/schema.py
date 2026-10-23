"""SQLite schema and ordered migrations (tracked by PRAGMA user_version)."""

V1 = """
CREATE TABLE source_files (
  path TEXT PRIMARY KEY, agent TEXT NOT NULL, fingerprint TEXT NOT NULL,
  parsed_at TEXT NOT NULL, status TEXT NOT NULL, detail TEXT
);
CREATE TABLE sessions (
  id TEXT PRIMARY KEY, agent TEXT NOT NULL, native_id TEXT NOT NULL,
  kind TEXT NOT NULL, parent_id TEXT, project_path TEXT, repo TEXT,
  title TEXT, started_at TEXT, ended_at TEXT, time_quality TEXT NOT NULL,
  agent_ref TEXT, source_path TEXT NOT NULL, meta_json TEXT NOT NULL
);
CREATE INDEX idx_sessions_parent ON sessions(parent_id);
CREATE INDEX idx_sessions_source ON sessions(source_path);
CREATE TABLE turns (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, seq INTEGER NOT NULL,
  started_at TEXT, ended_at TEXT, prompt_preview TEXT NOT NULL,
  prompt_chars INTEGER NOT NULL, outcome TEXT NOT NULL,
  source_path TEXT NOT NULL, source_line INTEGER NOT NULL
);
CREATE INDEX idx_turns_session ON turns(session_id, seq);
CREATE INDEX idx_turns_source ON turns(source_path);
CREATE TABLE usage_events (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_id TEXT, ts TEXT,
  model TEXT, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
  cache_write_tokens INTEGER NOT NULL, cache_read_tokens INTEGER NOT NULL,
  measurement TEXT NOT NULL, confidence TEXT NOT NULL, source TEXT NOT NULL,
  method TEXT, source_path TEXT NOT NULL, source_line INTEGER NOT NULL
);
CREATE INDEX idx_usage_turn ON usage_events(turn_id);
CREATE INDEX idx_usage_session ON usage_events(session_id);
CREATE INDEX idx_usage_source ON usage_events(source_path);
CREATE TABLE tool_calls (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_id TEXT, ts TEXT,
  name TEXT NOT NULL, target TEXT NOT NULL, is_error INTEGER,
  error_preview TEXT NOT NULL, source_path TEXT NOT NULL,
  source_line INTEGER NOT NULL
);
CREATE INDEX idx_tools_turn ON tool_calls(turn_id);
CREATE INDEX idx_tools_source ON tool_calls(source_path);
CREATE TABLE events (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_id TEXT, ts TEXT,
  kind TEXT NOT NULL, data_json TEXT NOT NULL, source_path TEXT NOT NULL,
  source_line INTEGER NOT NULL
);
CREATE INDEX idx_events_turn ON events(turn_id);
CREATE INDEX idx_events_source ON events(source_path);
CREATE TABLE tasks (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, title TEXT NOT NULL,
  started_at TEXT, ended_at TEXT, time_quality TEXT NOT NULL,
  boundary TEXT NOT NULL, confidence TEXT NOT NULL, evidence_json TEXT
);
CREATE INDEX idx_tasks_session ON tasks(session_id);
CREATE TABLE task_turns (
  task_id TEXT NOT NULL, turn_id TEXT NOT NULL,
  PRIMARY KEY (task_id, turn_id)
);
CREATE INDEX idx_task_turns_turn ON task_turns(turn_id);
CREATE TABLE collection_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_path TEXT, message TEXT,
  ts TEXT NOT NULL
);
CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

V2 = """
CREATE TABLE report_periods (
  period_id TEXT PRIMARY KEY, period_start TEXT NOT NULL,
  period_end TEXT NOT NULL, top_n INTEGER NOT NULL, status TEXT NOT NULL,
  generated_at TEXT NOT NULL, usage_hash TEXT, report_dir TEXT NOT NULL
);
CREATE TABLE analyses (
  cache_key TEXT PRIMARY KEY, period_id TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL, task_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL, path TEXT NOT NULL, status TEXT NOT NULL
);
CREATE INDEX idx_analyses_period ON analyses(period_id, created_at);
CREATE TABLE skill_changes (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, action TEXT NOT NULL,
  skill_name TEXT NOT NULL, scope TEXT NOT NULL, path TEXT NOT NULL,
  status TEXT NOT NULL, mode TEXT NOT NULL, base_hash TEXT,
  new_hash TEXT, backup_path TEXT, finding_json TEXT,
  applied_at TEXT, rolled_back_at TEXT, repo TEXT
);
CREATE INDEX idx_skill_changes_name ON skill_changes(skill_name);
"""

MIGRATIONS = [V1, V2]
