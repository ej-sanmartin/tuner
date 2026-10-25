# Progress

Last updated 2026-10-23. 77 automated tests pass on macOS (strict
encoding mode); ruff is clean.

## Done

| Phase | Scope | State |
| --- | --- | --- |
| 1 Collect | Claude (measured) and Cursor (estimated, enriched by state DB + hooks) adapters; SQLite; incremental/idempotent/locked collection; task attribution; reconciliation | Done; exercised on real local data |
| 2 Report | Deterministic `usage.json`; offline `report.html` (5 views); pricing with dated overrides | Done; HTML viewed in a browser (macOS) |
| 3 Schedule | Periods (DST-safe), catch-up/backfill, idempotent `schedule run`, launchd + Task Scheduler renderers, notifications, `init`/`doctor`/`uninstall` | Done in code; see "Not verified" |
| 4 Analysis | Cache key, evidence bundle with citable signals, validation (evidence, no money, injected costs), store, `/tuner` skill, `tuner analyze` | Done; driven end to end with a hand-written analysis |
| 5 Skills | Discovery, placement, validation, propose/apply/reject/rollback, backups, conflicts, managed-only writes, modes, effectiveness | Done; covered by tests |
| 6 Quality | Tests for every listed area, CI workflow, docs, README | Done except as noted |

## Verified on a real machine (macOS, 2026-10-23)

* `tuner init` (hooks, skill, collection) and `tuner schedule install`
  against the real home; the RunAtLoad launchd run generated four
  catch-up reports.
* `tuner upgrade` end to end, both in an isolated rehearsal (0.1.0 ->
  0.1.1 via local wheels) and on the real install (local checkout).
* A hand-written `/tuner`-style analysis saved and cached on real data.

## Not verified / open gaps (be skeptical here)

* **launchd calendar trigger does not fire on the dev Mac** (even a bare
  probe job). Mitigated, not fixed: the job also has an hourly
  `StartInterval` (verified to fire here: a 60 s trial gave runs=2 and a
  fresh heartbeat), and Cursor hooks (`sessionStart/End/stop`) start a
  detached, throttled `schedule run` when a report is due
  (`report.run_on_activity`). `doctor` shows the last run and warns about
  overdue reports. Windows' hourly repetition is XML-validated only.
* **macOS privacy (TCC):** an editable install under `~/Documents` made the
  scheduled job hang while Python started. `tuner doctor` now warns;
  use a non-editable install for the schedule.
* **PATH:** `uv tool` installs to `~/.local/bin`, which may not be on PATH
  (`uv tool update-shell`). Hooks and launchd use absolute paths, so they
  still work.
* **Windows**: nothing has run on Windows locally. CI found one real bug
  (UTF-8 vs cp1252 in tests), now guarded by strict encoding warnings.
  `schtasks`, toasts, `msvcrt` locking, and `tuner upgrade` on Windows
  (which prints manual steps because `tuner.exe` is locked) are untested.
* **`/tuner` in a live agent loop:** the analysis was driven by hand
  following the skill's steps, which exposed and fixed a `save`/`--top`
  mismatch. Evidence for one large task is ~50 KB, so analyzing many
  tasks is token-heavy; consider a compact mode.
* Published package: nothing uploaded to PyPI, so `tuner upgrade` for PyPI
  installs is only tested against local wheels.

## Known limitations

* Cursor tokens are estimates (documented method, low/medium confidence,
  `KNOWN_GAPS` listed in the data).
* Claude 1h-vs-5m cache-write pricing split and tiered long-context pricing
  are not modelled; historical usage uses current list prices unless dated
  overrides exist.
* `/clear` boundaries are not used for task grouping; continuation links
  are heuristic (interrupted turn or short prompt within 30 minutes).
* Subagent tree is one level deep (matches both collectors). Cursor
  subagents are labelled by their first prompt, since Cursor stores no
  subagent type or description locally.
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
