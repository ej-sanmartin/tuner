# Data schema

## Quality metadata

Every token figure carries `{value, measurement, source, confidence}`
(`measurement`: `measured`, `estimated`, `unavailable`). Aggregates report
the weakest measurement they contain.

## SQLite (`PRAGMA user_version` = 2)

| Table | Purpose |
| --- | --- |
| `source_files` | path, agent, fingerprint, status (change detection) |
| `sessions` | agent, native id, kind (main/subagent), parent, repo, times, `time_quality` |
| `turns` | one user prompt: redacted preview (<=240 chars), char count, outcome, source line |
| `usage_events` | one model call: disjoint `input/output/cache_write/cache_read` tokens, model, measurement, confidence, method, source line |
| `tool_calls` | name, redacted target, `is_error` (NULL = unknown), error preview |
| `events` | `subagent_spawn`, `compaction`, ... with small JSON payloads |
| `tasks`, `task_turns` | attribution; evidence JSON explains grouping |
| `report_periods` | generated periods (`complete`/`partial`), usage hash |
| `analyses` | cache key, period, snapshot hash, status (`valid/superseded/invalidated`) |
| `skill_changes` | proposals and changes: status, hashes, backup path, finding JSON |
| `collection_errors`, `kv` | diagnostics, last-collect time |

Token categories are disjoint, so `total = input + output + cache_write +
cache_read` and cost is a plain weighted sum.

## `usage.json` (`schema_version` 1, `kind: tuner.usage`)

`period`, `selection`, `overview` (tokens, quality, counts, by_agent,
by_model, cost), `tasks[]` (rank, tokens, models, quality, outcome, tools,
subagents, compactions, grouping, cost, timeline, sources),
`data_quality` (reconciliation, gaps), `pricing.meta`, `privacy` statement.

## `analysis.json` (`schema_version` 1, `kind: tuner.analysis`)

`cache_key`, `snapshot_hash`, `produced_by`, `coverage {selected,analyzed}`,
`tasks[]` (objective, summary, what_happened, classification into
`productive_complexity` / `avoidable_overhead` / `insufficient_evidence`,
injected `cost`), `recommendations[]` (kind, scope, confidence, evidence
with refs, status set by Tuner, destination and diff for skill changes),
`limitations`. `tuner analyze schema` prints the input template.

## Pricing

Bundled LiteLLM-derived snapshot -> optional refreshed cache -> dated user
overrides in `pricing_overrides.toml` (`[[model]]` with `id`, `provider`,
`input/output/cache_write/cache_read` per million USD, `effective_from`).
Unknown models give `complete: false`. Costs are API-equivalent estimates,
not billing.

## Configuration

`tuner config show` prints every option with defaults (sections: report,
sources, attribution, analysis, skills, delivery, privacy).
