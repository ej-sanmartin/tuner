# Temporary backlog (delete items as they land; delete file when empty)

- `tuner init`: print a hint to run `uv tool update-shell` when
  `~/.local/bin` is not on PATH.
- Apply one real skill proposal end to end and check effectiveness
  tracking on real data.
- Linux support: systemd user timer (with `Persistent=true`), paths and
  notifications.
- (Deferred) Live `/tuner` run in Cursor and Claude Code, compact evidence
  mode, skill-text tuning.
- After the first PyPI release, test `tuner upgrade` against the real
  index.
- Possible: Claude Code `SessionEnd` hook to tick like Cursor hooks.
- Thread rollups (sum tokens across a `thread_id`) in `usage.json`/HTML.
- Hold out a new dashboard week (`tuner import cursor --fetch`, then
  `doctor`) and re-fit only if the error moved. Per-model system prompt
  size is the candidate (Claude low, composer high).
- Dashboard requests that match no turn (about 1% of tokens on the
  2026-10-26 export, start time more than 3s from any turn).
