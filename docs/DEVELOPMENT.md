# Development

```sh
uv sync
uv run pytest                 # unit + integration (synthetic fixtures)
uv run ruff check src tests
uv run tuner --help
```

* Tests never touch your real home: the `env` fixture sets `TUNER_FAKE_HOME`
  and `TUNER_HOME` to temp dirs, and OS scheduler calls are skipped under
  `TUNER_FAKE_HOME`. Use the same variables for manual experiments:
  `TUNER_HOME=/tmp/t TUNER_FAKE_HOME=/tmp/h uv run tuner init`.
* Fixtures are synthetic builders in `tests/fixtures/builders.py`; never
  commit real transcripts.
* Style: Google style, 80 columns (hard limit 100), docstring on every
  function (usage, params, returns), files under 300 lines, no duplicated
  helpers. Ruff lint is enforced; `ruff format` is intentionally not.
* Add an agent: implement `UsageCollector`, register it in
  `collectors/__init__.py`, add a builder fixture and parser tests.
* Refresh bundled prices: `uv run python scripts/refresh_pricing_snapshot.py`
  (network).
* The wheel force-includes `agent-skills/` as `tuner/_agent_skills`; keep
  `SKILL.md` valid per the Agent Skills spec.
* CI (`.github/workflows/ci.yml`) runs lint, tests, and a wheel smoke test
  on macOS and Windows. Changes only under `docs/**`, `README.md`, or
  `AGENTS.md` do not start it. `agent-skills/` still does: the wheel
  smoke test checks that `SKILL.md` is packaged.

## Versions, upgrades, and releases

* The version lives only in `src/tuner/__init__.py` (hatch reads it).
* `tuner upgrade` supports `uv tool`, `pipx`, and local-checkout installs
  (`uv tool install --force --reinstall <dir>` after `git pull`). Editable
  installs work for development, but on macOS a launchd job cannot read
  `~/Documents`, `~/Desktop`, or `~/Downloads`, so a scheduled run from an
  editable install there hangs; use a non-editable install for the
  schedule (`tuner doctor` warns).
* Rehearse an upgrade without touching your machine: build two versions
  into a temp dir, then use `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`,
  `UV_FIND_LINKS=<dir> UV_NO_INDEX=1`, `TUNER_HOME`, and `TUNER_FAKE_HOME`
  with `uv tool install agent-tuner` / `tuner upgrade`.
* Release: bump `__version__`, add a `CHANGELOG.md` entry, merge to
  `main`, then `git tag v<version> && git push --tags`.
  `.github/workflows/release.yml` re-runs CI, checks the tag equals the
  version, builds, checks the wheel and sdist (`scripts/check_wheel.py`),
  publishes to PyPI by trusted publishing (environment `pypi`, no token),
  and creates the GitHub release. `tuner upgrade` picks it up from the
  index. Setup steps are at the top of the workflow file.
