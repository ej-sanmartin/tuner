# Changelog

## 1.0.0

First public release on PyPI as `agent-tuner` (command: `tuner`).

- Collects usage from Cursor (estimated), Claude Code, OpenCode, Open
  WebUI, and Hermes (measured); deterministic `usage.json` and an
  offline `report.html`.
- `/tuner` Agent Skill, scheduled weekly reports on macOS and Windows,
  skill proposals with review, apply, and rollback.
- `tuner init` writes a config with every default commented out, so
  later default changes reach existing installs.
- `tuner upgrade` supports `uv tool` and `pipx`.
