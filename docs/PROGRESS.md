# Progress

Last updated 2026-10-22. 56 automated tests pass on macOS; ruff is clean.

## Done

| Phase | Scope | State |
| --- | --- | --- |
| 1 Collect | Claude (measured) and Cursor (estimated, enriched by state DB + hooks) adapters; SQLite; incremental/idempotent/locked collection; task attribution; reconciliation | Done; exercised on real local data |
| 2 Report | Deterministic `usage.json`; offline `report.html` (5 views); pricing with dated overrides | Done; HTML viewed in a browser (macOS) |
| 3 Schedule | Periods (DST-safe), catch-up/backfill, idempotent `schedule run`, launchd + Task Scheduler renderers, notifications, `init`/`doctor`/`uninstall` | Done in code; see "Not verified" |
| 4 Analysis | Cache key, evidence bundle with citable signals, validation (evidence, no money, injected costs), store, `/tuner` skill, `tuner analyze` | Done; driven end to end with a hand-written analysis |
| 5 Skills | Discovery, placement, validation, propose/apply/reject/rollback, backups, conflicts, managed-only writes, modes, effectiveness | Done; covered by tests |
| 6 Quality | Tests for every listed area, CI workflow, docs, README | Done except as noted |

## Not verified (be skeptical here)

* **Windows**: nothing has run on Windows. The Task Scheduler XML is
  parsed in tests but `schtasks` was never invoked; toast notifications,
  `msvcrt` locking, and path handling are untested. CI is configured for
  `windows-latest` but has not run yet; expect first-run fixes.
* **Real OS scheduler on macOS**: tests and experiments run with
  `TUNER_FAKE_HOME`, which deliberately skips `launchctl`. `tuner schedule
  install` against real launchd has not been run on this machine.
* **Real Cursor hooks**: install/uninstall is tested against temp files; it
  has not modified the real `~/.cursor/hooks.json`.
* **`/tuner` inside Cursor/Claude Code**: the skill text is written and the
  CLI contract is tested, but no live agent has followed it yet. Expect
  wording tweaks after the first real run.
* **Published package**: `uv build` works and the wheel contains the skill,
  templates, and price snapshot; it has not been uploaded to PyPI.

## Known limitations

* Cursor tokens are estimates (documented method, low/medium confidence,
  `KNOWN_GAPS` listed in the data).
* Claude 1h-vs-5m cache-write pricing split and tiered long-context pricing
  are not modelled; historical usage uses current list prices unless dated
  overrides exist.
* `/clear` boundaries are not used for task grouping.
* Scheduled runs cannot run analysis unattended (no in-process LLM by
  design); they produce the report and a notification pointing to `/tuner`.
* Effectiveness is observational (before/after medians, sample sizes), never
  a causal claim.
* Linux: paths and notifications are stubbed; no scheduler yet.

## Next

1. Run Windows CI, fix what breaks.
2. Install the schedule and hooks for real on a dev machine; run `/tuner`
   in both agents; refine the skill text from what the agents actually do.
3. Optional headless "provider" interface for unattended analysis.
4. Linux support (systemd user timer).
