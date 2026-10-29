# Privacy and security

## What Tuner reads

* Claude Code transcripts (`~/.claude/projects`, `CLAUDE_CONFIG_DIR`, extra
  dirs from config, WSL homes on Windows).
* Cursor transcripts (`~/.cursor/projects/*/agent-transcripts`), Cursor's
  `state.vscdb` (opened **read-only**), and Tuner's own hook spool.
* Existing skills directories (to avoid overlap), and names of project
  guidance files (`AGENTS.md`, `.cursor/rules/*`; never their contents).

## What Tuner stores

In its own data dir (owner-only permissions where the OS supports it):
redacted prompt previews (<=240 chars), tool names and redacted targets,
token counts, timings, hashes. It does **not** store full prompts,
responses, tool outputs, or file contents. Hook events keep only an
allow-list of fields (prompt *length*, never text).

`report.html` re-reads each shown task's prompts from the transcript,
redacts them, and embeds them so the task page can show what was typed.
That file stays in Tuner's data directory.

## What a model may see

Only the output of `tuner analyze evidence`, run by your own agent: the
stored previews plus bounded, redacted excerpts re-read on demand from the
local transcript (first prompts <=1500 chars, final response <=800 chars).
Set `privacy.analysis_excerpts = false` to withhold excerpts entirely.
The bundle is labelled untrusted data.

## Network

None by default, no telemetry, no listeners. The one exception is
`tuner pricing refresh` (downloads a public price list; sends no usage
data; requires `--allow-network` while `privacy.local_only = true`).

## Untrusted input

Transcripts may contain prompt-injection text. Defences: the skill tells the
agent to treat evidence as data; analysis output is schema-validated with
existing evidence refs; generated skills are validated (format, secrets,
risky instruction patterns, size) before they can be applied; the model
cannot set recommendation status or costs.

## File safety

* Only managed hooks (`--tuner-managed`), the managed `/tuner` skill, and
  skills created by Tuner (metadata `tuner-managed: "true"`) are ever
  modified or removed. Unmanaged, third-party, and built-in skills are
  never changed (changes become manual proposals).
* Atomic writes, backups before overwrite, base-hash conflict detection,
  rollback (refuses if you edited the file since, unless `--force`).
* Destinations are confined to the chosen skills directory; names with
  path separators or `..` are rejected.
* Tuner never runs `git add` or `git commit`, and never edits source code to
  save tokens. Cursor `hooks.json` is backed up once and refused if invalid.
* Secret redaction is best-effort defence in depth (built-in patterns plus
  `privacy.redact_patterns`), not a guarantee.

## Removing everything

`tuner uninstall` removes hooks, the skill, and the schedule;
`--purge-data` also deletes the database, reports, and config.
