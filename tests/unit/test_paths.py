"""Platform-appropriate directories."""

import sys
from pathlib import Path

from tuner import paths


def dirs(monkeypatch, platform, **env):
    monkeypatch.delenv("TUNER_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return paths.config_dir(), paths.data_dir()


def test_macos_dirs(monkeypatch, env):
    cfg, data = dirs(monkeypatch, "darwin")
    assert cfg == env / "Library" / "Application Support" / "tuner"
    assert data == cfg


def test_windows_dirs_use_appdata(monkeypatch, env):
    cfg, data = dirs(monkeypatch, "win32", APPDATA=str(env / "R"),
                     LOCALAPPDATA=str(env / "L"))
    assert cfg == Path(env / "R" / "tuner")
    assert data == Path(env / "L" / "tuner")


def test_linux_dirs_follow_xdg(monkeypatch, env):
    cfg, data = dirs(monkeypatch, "linux", XDG_CONFIG_HOME=str(env / "c"),
                     XDG_DATA_HOME=str(env / "d"))
    assert cfg == env / "c" / "tuner" and data == env / "d" / "tuner"


def test_tuner_home_override(monkeypatch, env, tmp_path):
    monkeypatch.setenv("TUNER_HOME", str(tmp_path / "x"))
    assert paths.db_file() == tmp_path / "x" / "data" / "tuner.db"
