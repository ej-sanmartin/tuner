# Temporary backlog (delete items as they land; delete file when empty)

- `tuner init`: print a hint to run `uv tool update-shell` when
  `~/.local/bin` is not on PATH.
- Apply one real skill proposal end to end and check effectiveness
  tracking on real data.
- Linux support: systemd user timer (with `Persistent=true`), paths and
  notifications.
- (Deferred) Live `/tuner` run in Cursor and Claude Code, compact evidence
  mode, skill-text tuning.
- (Deferred) PyPI publish + release workflow, then test `tuner upgrade`
  against the real index.
- Possible: Claude Code `SessionEnd` hook to tick like Cursor hooks.
- Before publishing: `init` writes every default into config.toml, which
  pins old defaults and breaks on renamed keys (hit when `merge_followups`
  became `link_followups`). Write only non-default keys, or add a rename
  migration in `sync`.
- Thread rollups (sum tokens across a `thread_id`) in `usage.json`/HTML.
- Re-fit Cursor estimates when a new CSV is available (hold out a week
  to check the in-sample numbers); consider per-model system prompt size
  (Claude low, composer high).
- Optional `tuner import cursor-csv <file>`: store the dashboard's exact
  per-request tokens as measured data and show estimate error in doctor.
- Turns the CSV shows with no steps in our data (about 20), and 21 CSV
  requests with no turn (about 1% of tokens): find what they are.
