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
  on macOS and Windows.
