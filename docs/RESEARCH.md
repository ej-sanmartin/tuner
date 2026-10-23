# Research notes

What we studied, what we reused (ideas only), what is missing, and the
tradeoffs behind Tuner's design. **No third-party source code was copied
into Tuner**; the rows below say what idea each project informed. Gap
columns reflect each project's public description and were not verified
by running the tools. Licenses
are noted so any future reuse is a conscious decision.

## Prior art

| Project | License | What we took from it | Gap for Tuner's goals |
| --- | --- | --- | --- |
| [ccusage](https://github.com/ccusage/ccusage) | MIT (LICENSE file; not auto-detected by GitHub) | Claude Code JSONL usage accounting; per-request de-duplication; cost from token categories | Claude-focused, Node/`npx` runtime; no Cursor, task attribution, or skills loop |
| Claude `session-report` plugin | Apache-2.0 | Session/subagent/tool breakdown ideas; self-contained HTML report | Claude only; no persistence, cache, or optimisation loop |
| [LiteLLM price list](https://github.com/BerriAI/litellm) | MIT for the public repo (its `enterprise/` dir is separately licensed; we use only the public price JSON) | Per-model price table (bundled snapshot, explicit refresh) | Current prices only; we add dated user overrides |
| [code-insights](https://github.com/melagiri/code-insights) | MIT | "Turn AI coding sessions into knowledge": session-to-insight idea | Not analysed in depth; we found no deterministic snapshot/cache design |
| [ai-coding-usage-tracker](https://github.com/SuvenSeo/ai-coding-usage-tracker) | MIT | Local-first multi-tool (Codex, Claude Code, Cursor) usage dashboard; confirms demand | Dashboard-oriented per its description; nothing indicates task attribution or skill optimisation |
| [codex-usage-tracker](https://github.com/MEETDesai011/codex-usage-tracker) | MIT | Similar local-first multi-agent usage dashboard | Same as above |
| [cursor/plugins `reflect` skill](https://github.com/cursor/plugins/blob/main/pstack/skills/reflect/SKILL.md) | no license published | Shape of a reflective skill | No license means no reuse; conceptual only |
| Agent Skills spec ([agentskills.io](https://agentskills.io/), [Claude](https://code.claude.com/docs/en/skills), [Cursor](https://cursor.com/docs/skills)) | n/a | SKILL.md format, discovery paths, frontmatter limits | — |
| [Cursor hooks](https://cursor.com/docs/hooks) | n/a | Event payloads for timestamps, compaction, subagents | Hooks carry no token counts |

## What nothing else does together

* One local database across Cursor **and** Claude Code with explicit
  measured/estimated quality labels.
* Task-level attribution (turns -> tasks -> subagents) that reconciles to
  session totals and reports what it could not attribute.
* A deterministic snapshot that an LLM can analyse **on demand**, cached by
  a content-derived key, with the LLM prevented from inventing costs.
* A skill-optimisation loop with backups, conflict detection, rollback, and
  observational effectiveness tracking.

## Platform findings

* **Claude Code** writes per-session JSONL with provider `usage`; one API
  response is streamed across several lines (keep max `output_tokens` per
  `requestId`); resumed sessions replay earlier lines (de-duplicate by
  `uuid`); subagents live in their own files and the Task tool's
  `totalTokens` is only a hint.
* **Cursor** stores agent transcripts (JSONL, no usage) under
  `~/.cursor/projects/*/agent-transcripts`, and richer per-message data
  (timestamps, model, thinking, tool status, subagent links) in its
  `state.vscdb` SQLite file, read **read-only**. The `tokenCount` fields are
  zero in observed data, so tokens are estimated; hooks add timestamps and
  compaction events.
* Skill locations: `.claude/skills` is read by both apps, so it is the
  canonical write target; `.cursor/skills` and `.agents/skills` are scanned
  for overlap but not written.

## Tradeoffs

* **Python 3.13 + uv, zero runtime deps.** Easy `uv tool install`, no Node,
  stdlib `sqlite3`/`tomllib`/`zoneinfo`. Cost: hand-rolled frontmatter and
  TOML-edit helpers (small and tested).
* **PyPI name.** `tuner` is taken; distribution `agent-tuner`, command
  `tuner`.
* **No in-process LLM.** The `/tuner` skill reuses the user's current agent,
  so no API key and no second bill. Cost: analysis cannot run unattended
  (scheduled runs produce the deterministic report and a notification).
  A provider interface can be added later.
* **Estimates over silence for Cursor.** Better to show a labelled,
  low-confidence estimate with known gaps than nothing; never summed with
  measured data silently.
* **Current list prices on historical usage** unless the user adds dated
  overrides; stated in every cost's limitations. Tiered long-context
  pricing is not modelled.
* **Effectiveness is correlation.** Before/after medians with sample sizes;
  verdicts are "possible", never "proven".
