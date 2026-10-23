"""Upgrade: install-method detection and integration sync."""

import sys

import pytest

from tuner import __version__, config
from tuner.commands import upgrade
from tuner.commands.common import TunerError
from tuner.integrations import cursor_hooks, skill_install, sync
from tuner.storage import connect


def test_sync_refreshes_only_what_is_installed(env):
    (env / ".cursor").mkdir()
    cfg = config.load()
    names = [n for n, _ in sync.sync(cfg)]
    assert names == ["database"]  # nothing opted in -> nothing added
    assert not skill_install.target_dir().exists()
    skill_install.install()
    names = [n for n, _ in sync.sync(cfg)]
    assert "/tuner skill" in names and "cursor hooks" not in names


def test_sync_updates_stale_skill_and_marks_version(env):
    skill_install.install()
    skill = skill_install.target_dir() / "SKILL.md"
    skill.write_text(skill.read_text("utf-8").replace(
        __version__, "0.0.1"), "utf-8")
    conn = connect()
    assert sync.needs_sync(conn) == "unknown"
    sync.sync(config.load())
    assert __version__ in skill.read_text("utf-8")
    assert sync.needs_sync(connect()) is None


def test_sync_repoints_hooks_to_current_executable(env, monkeypatch):
    (env / ".cursor").mkdir()
    cursor_hooks.install()
    monkeypatch.setattr("tuner.integrations.exe.tuner_argv",
                        lambda: ["/new/path/tuner"])
    monkeypatch.setattr("tuner.integrations.cursor_hooks.tuner_command",
                        lambda *a: " ".join(["/new/path/tuner", *a]))
    sync.sync(config.load())
    text = (env / ".cursor" / "hooks.json").read_text("utf-8")
    assert "/new/path/tuner hook stop" in text


@pytest.mark.parametrize("prefix,expected", [
    ("/Users/x/.local/share/uv/tools/agent-tuner", "uv-tool"),
    ("/Users/x/.local/pipx/venvs/agent-tuner", "pipx"),
    ("/opt/venv", "other"),
])
def test_install_method_detection(monkeypatch, prefix, expected):
    monkeypatch.setattr(sys, "prefix", prefix)
    monkeypatch.setattr(upgrade.md, "distribution",
                        lambda n: type("D", (), {
                            "read_text": lambda self, f: None})())
    assert upgrade.install_method()[0] == expected


def test_editable_install_detected(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "prefix", "/x/uv/tools/agent-tuner")
    monkeypatch.setattr(upgrade.md, "distribution", lambda n: type(
        "D", (), {"read_text": lambda self, f: (
            '{"url": "file:///src/tuner", "dir_info": {"editable": true}}'
        )})())
    assert upgrade.install_method() == ("editable-uv", "/src/tuner")
    monkeypatch.setattr(upgrade.md, "distribution", lambda n: type(
        "D", (), {"read_text": lambda self, f: (
            '{"url": "file:///src/my%20tuner", "dir_info": {}}')})())
    assert upgrade.install_method() == ("path-uv", "/src/my tuner")


def test_windows_drive_path_detected(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "prefix", "C:/x/uv/tools/agent-tuner")
    monkeypatch.setattr(upgrade.md, "distribution", lambda n: type(
        "D", (), {"read_text": lambda self, f: (
            '{"url": "file:///C:/src/tuner", "dir_info": {}}')})())
    assert upgrade.install_method() == ("path-uv", "C:/src/tuner")


def test_upgrade_commands_per_method(monkeypatch):
    ran = []
    monkeypatch.setattr(upgrade, "_run", ran.append)
    monkeypatch.setattr(upgrade, "_need", lambda exe: exe)
    monkeypatch.setattr(sys, "platform", "darwin")
    upgrade.upgrade_package("uv-tool", "")
    upgrade.upgrade_package("pipx", "")
    upgrade.upgrade_package("editable-uv", "/src/tuner")
    upgrade.upgrade_package("path-uv", "/src/tuner")
    assert ran[0] == ["uv", "tool", "upgrade", "agent-tuner"]
    assert ran[1] == ["pipx", "upgrade", "agent-tuner"]
    assert ran[2][:5] == ["git", "-C", "/src/tuner", "pull", "--ff-only"]
    assert ran[3][-2:] == ["--editable", "/src/tuner"]
    assert ran[5][-3:] == ["--force", "--reinstall", "/src/tuner"]
    with pytest.raises(TunerError, match="pip install"):
        upgrade.upgrade_package("other", "")


def test_windows_uv_tool_gives_manual_steps(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(TunerError, match="--sync-only"):
        upgrade.upgrade_package("uv-tool", "")
