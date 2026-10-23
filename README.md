# Tuner

**Understand your AI usage. Tune your agent workflows.**

Tuner is a local-first tool that reads the session history of your coding
agents (Cursor and Claude Code today), shows where your tokens went, and
helps you turn the expensive patterns into better prompts, rules, and
Agent Skills. It runs on macOS and Windows with Python 3.13 and has **no
runtime dependencies, no cloud service, and no API key**.

> Status: alpha (0.1.0). See [docs/PROGRESS.md](docs/PROGRESS.md) for what
> is done, what is verified, and what is not.

## Install

```sh
uv tool install agent-tuner   # installs the `tuner` command
tuner init                    # config, Cursor hooks, /tuner skill, schedule
```

(`tuner` is taken on PyPI, so the distribution is `agent-tuner`; the
command is `tuner`.) `tuner init` is explicit and reversible with
`tuner uninstall`; skip pieces with `--no-hooks --no-skill --no-schedule`.

## Use

```sh
tuner report --open      # collect new usage, build and open the report
tuner doctor             # check sources, hooks, skill, schedule
```

Then, in Cursor or Claude Code, run **`/tuner`**. The agent reads a
redacted evidence bundle, explains *why* the expensive tasks were
expensive (productive complexity vs avoidable overhead vs insufficient
evidence), and proposes improvements. The result is cached and appears in
the report's Recommendations view. Re-running `/tuner` on unchanged data
reuses the cache instead of spending tokens again.

Reports land in `reports/<period>/{usage.json,analysis.json,report.html}`
inside Tuner's data directory (`tuner open --path` prints the latest
report's location). They are
generated every Sunday at 18:00 local time by default, with catch-up if the
machine was off.

| Command | Purpose |
| --- | --- |
| `tuner init` / `uninstall` | set up / remove everything Tuner installed |
| `tuner collect` | incremental, idempotent import (no LLM) |
| `tuner report` | deterministic `usage.json` + offline `report.html` |
| `tuner analyze` | cache status, evidence, save analysis (used by `/tuner`) |
| `tuner skills` | list, diff, apply, reject, roll back skill changes |
| `tuner schedule` | install/inspect the OS job; `run` is idempotent |
| `tuner pricing` | price lookups and deterministic cost math |
| `tuner config` | show/edit validated TOML config |
| `tuner open`, `tuner doctor` | open latest report; diagnostics |

## What is measured and what is estimated

Claude Code transcripts contain provider usage, so those numbers are
**measured**. Cursor does not store token counts locally, so Cursor numbers
are **estimates** (labelled, with a method, confidence, and known gaps) and
are never mixed with measured data without saying so. Costs are
API-equivalent estimates from versioned prices, not billing; unknown models
produce an explicitly incomplete estimate. See
[docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md).

## Skills Tuner may create

Modes (`tuner config set skills.mode review`): `suggest` (record only),
`review` (default; you apply with `tuner skills apply ID`), `auto` (small,
validated changes only). Tuner only edits skills it created, backs up
before writing, detects conflicts, supports `tuner skills rollback`, and
never runs `git add` or `git commit`. See [docs/PRIVACY.md](docs/PRIVACY.md).

## Privacy in one paragraph

Everything stays on your machine. No telemetry. The only network request
Tuner can make is `tuner pricing refresh` (public price list, explicit and
opt-in). Transcripts are treated as untrusted data and are redacted for
secrets. The model only sees what `tuner analyze evidence` prints.

## Docs

[Research](docs/RESEARCH.md) · [Architecture](docs/ARCHITECTURE.md) ·
[Data schema](docs/DATA_SCHEMA.md) · [Privacy](docs/PRIVACY.md) ·
[Development](docs/DEVELOPMENT.md) · [Progress](docs/PROGRESS.md)

## License

MIT
