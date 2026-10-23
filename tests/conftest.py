"""Shared fixtures: isolated home/config/data directories."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures import builders  # noqa: E402,F401


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated fake home + Tuner home; returns the fake home path."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("TUNER_FAKE_HOME", str(home))
    monkeypatch.setenv("TUNER_HOME", str(tmp_path / "tuner"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    from tuner.scheduler import tick
    tick.spawned = []  # record, never spawn, activity ticks
    monkeypatch.setattr(tick, "_popen", tick.spawned.append)
    return home


@pytest.fixture
def conn(env):
    """Fresh migrated database."""
    from tuner.storage import connect
    c = connect()
    yield c
    c.close()
