# Architecture

Six components with narrow interfaces. Only step 5 involves an LLM, and it
runs inside the user's own agent.

```
 agent files ──► 1 Collectors ──► 2 Store/Attribution ──► 3 Snapshot ──► 6 Report
 (Cursor, Claude)   (adapters)      (SQLite, tasks)       (usage.json)   (HTML)
                                                              │
                              5 Skill optimizer ◄── 4 Analysis (on demand, cached)
                              (propose/apply/rollback)   via the /tuner skill
```

## 1. Collectors (`tuner.collectors`)

`UsageCollector` protocol: `discover`, `locations`, `iter_sources`,
`parse`, `capabilities`. A new agent is one class registered in
`build_collectors`. Parsers never raise on malformed input; problems are
returned in `ParsedSource.errors`.

* `claude*.py`: measured usage. De-duplicates streamed lines by
  `requestId`/`message.id`, skips replayed `uuid`s, makes subagent files
  child sessions linked to the spawning turn.
* `cursor*.py`: transcripts + read-only `state.vscdb` enrichment + hook
  spool. Tokens are estimated (`cursor_estimate.py`) with documented
  methods and `KNOWN_GAPS`; if Cursor ever stores real counts they are used
  as measured.

## 2. Store and attribution (`tuner.storage`, `tuner.attribution`)

SQLite (WAL). `collect.py` takes a cross-platform file lock, then for each
changed source file atomically replaces its rows (`DELETE` by
`source_path`, `INSERT OR IGNORE`). Change detection is a cheap fingerprint
(`size:mtime_ns:salt`), so re-runs are no-ops and nothing is double counted.
`attribution/tasks.py`: a task is one user prompt plus everything the agent
did for it. Every human prompt is its own task (never merged). Harness
messages nobody typed (post-compaction summary, empty notification
wrapper, background-task completion ping) join the previous task as
`system_turns`, so the workflow that caused them keeps the cost. A prompt may carry
a `continues` link to the previous task (previous turn interrupted/errored,
or a short affirmation such as "yes ..." within `idle_gap_minutes`,
default 30) with rule and gap;
linked tasks share a `thread_id`. Task ids are `task:` + sha1 of the first
turn id, so they are stable. Changing the grouping rules or config makes
the next collect regroup everything (`attribution_rules` in `kv`).
Subagent usage is attributed through spawn events to the task whose turn
spawned them; `load_task_subtasks` returns that workflow tree (task ->
subagents, depth 1: both collectors record children against the main
session). Reconciliation reports what could not be attributed.

## 3. Snapshot (`tuner.reports.snapshot`)

Pure function of the database + pricing + config -> `usage.json` (versioned,
stable ordering, no volatile fields in its content hash). Contains top-N
tasks (detail kept for at least 25), per-model/category tokens, quality
labels, coverage gaps, and source refs; no full prompts.

## 4. Analysis (`tuner.analysis`, `agent-skills/tuner`)

Tuner never calls a model. The `/tuner` skill drives the CLI:
`analyze status` (cache key) -> `analyze evidence` (redacted bundle with
citable ids `S#` signals, `T#` timeline, `P#` prompts) -> the agent writes
an analysis -> `analyze save` validates it. The cache key hashes: snapshot
content, selected task ids, instructions version + bundled skill text,
pricing version (snapshot meta + overrides file), and relevant config.
Validation requires evidence refs that exist, bounds all text, rejects
dollar amounts, ignores model-supplied costs (deterministic cost is
injected), and makes the CLI, not the model, decide recommendation status.

## 5. Skill optimizer (`tuner.skills`)

`placement` (global vs project; canonical `.claude/skills`), `validate`
(format, secrets, risky instructions, overlap), `lifecycle`
(propose/apply/reject/rollback with backups, base-hash conflict detection,
change log, managed-only writes), `evaluate` (cautious before/after).
Modes: `suggest` records only; `review` needs `tuner skills apply`; `auto`
applies only validated, warning-free, small changes to managed targets.

## 6. Report and delivery (`tuner.reports`, `scheduler`, `notifications`)

`report.html` is one offline file: static template + embedded JSON escaped
for `<script>`, DOM built only with `textContent`, CSP blocking network.
`tuner schedule run` is idempotent (lock + `report_periods`) and does
collect -> due periods -> generate -> notify. launchd (`StartCalendarInterval`
+ `RunAtLoad` + hourly `StartInterval`) and Task Scheduler
(`StartWhenAvailable` + logon + hourly repetition) only call that command,
so catch-up works after sleep or downtime. Cursor hooks are a third,
timer-independent trigger: `scheduler/tick.py` compares now with a
`next_due` file and spawns a detached run. Each run writes a heartbeat
(`last_schedule_run`) that `doctor` checks. Periods
are computed on wall-clock time in the configured timezone and converted to
UTC at the edges, which keeps them contiguous across DST.

## Cross-cutting

* `config.py`: schema-driven TOML with validation and comment-preserving
  edits. `paths.py`: platform dirs; `TUNER_HOME`/`TUNER_FAKE_HOME` for
  tests (OS schedulers are never touched under `TUNER_FAKE_HOME`).
* `security/redact.py`: secrets masked before storage/export.
* `hook_spool.py`: import-light; responds first, spools allow-listed
  fields only, always exits 0.
