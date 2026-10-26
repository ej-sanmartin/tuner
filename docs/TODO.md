# Temporary backlog (delete items as they land; delete file when empty)

- `tuner init`: print a hint to run `uv tool update-shell` when
  `~/.local/bin` is not on PATH.
- Apply one real skill proposal end to end and check effectiveness
  tracking on real data.
- Compare Cursor token estimates with ground truth (Cursor dashboard).
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
- Calibrate Cursor token estimates per task against ground truth
  (agreed next step after the workflow tree).
- Thread rollups (sum tokens across a `thread_id`) in `usage.json`/HTML.
- Calibration data: export the Cursor dashboard usage CSV (per-request
  tokens by category) for the last week, match requests to tasks by time
  and model, and tune the tool-result cap from hundreds of points.
- Cursor model per turn: a conversation's model is read from the composer's
  *current* setting, so switching models mid-chat relabels earlier steps
  (seen on 2026-10-26: sonnet turns became grok). Use the per-prompt model
  from `beforeSubmitPrompt` hook events when they align with turns.
