"""Cursor hooks/spool, skill installation, config, redaction, HTML."""

import io
import json

import pytest

from tuner import config, hook_spool
from tuner.integrations import cursor_hooks, skill_install
from tuner.reports.html import safe_json
from tuner.security.redact import redact

U8 = "utf-8"


def test_hooks_install_is_idempotent_and_preserves_user_hooks(tmp_path):
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps({"version": 1, "extra": 1, "hooks": {
        "stop": [{"command": "./mine.sh"}]}}), U8)
    cursor_hooks.install(path)
    cursor_hooks.install(path)
    data = json.loads(path.read_text(U8))
    assert data["extra"] == 1
    assert len(data["hooks"]["stop"]) == 2  # mine + ours, never duplicated
    assert {"command": "./mine.sh"} in data["hooks"]["stop"]
    cursor_hooks.uninstall(path)
    data = json.loads(path.read_text(U8))
    assert data["hooks"] == {"stop": [{"command": "./mine.sh"}]}
    assert cursor_hooks.installed_events(path) == []


def test_hooks_refuse_to_modify_invalid_json(tmp_path):
    path = tmp_path / "hooks.json"
    path.write_text("{not json", U8)
    with pytest.raises(cursor_hooks.HooksError):
        cursor_hooks.install(path)
    assert path.read_text(U8) == "{not json"


def test_hook_spools_allowlisted_fields_and_fails_open(env):
    out = io.StringIO()
    payload = {"conversation_id": "c1", "prompt": "SECRET PROMPT TEXT",
               "model": "m", "api_key": "sk-abcdefghijklmnopqrstuv"}
    assert hook_spool.run_hook("beforeSubmitPrompt", json.dumps(payload),
                               out) == 0
    assert json.loads(out.getvalue()) == {"continue": True}
    raw = hook_spool.spool_file().read_text(U8)
    assert "SECRET" not in raw and "sk-" not in raw
    assert json.loads(raw)["prompt_chars"] == len("SECRET PROMPT TEXT")
    bad = io.StringIO()
    assert hook_spool.run_hook("stop", "{{{garbage", bad) == 0
    assert json.loads(bad.getvalue()) == {}


def test_skill_install_roundtrip_and_never_overwrites_unmanaged(env):
    dest = skill_install.install()
    assert skill_install.is_managed(dest)
    skill_install.install()  # idempotent refresh
    assert skill_install.uninstall() and not dest.exists()
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("---\nname: tuner\ndescription: mine\n"
                                   "---\nbody\n", U8)
    with pytest.raises(FileExistsError):
        skill_install.install()
    assert not skill_install.uninstall()
    assert (dest / "SKILL.md").exists()


def test_config_set_preserves_comments_and_validates(env):
    config.write_default()
    path = config.paths.config_file()
    path.write_text("# my note\n" + path.read_text(U8), U8)
    config.set_value("report", "top_n", "7")
    text = path.read_text(U8)
    assert text.startswith("# my note") and config.load().report.top_n == 7
    with pytest.raises(config.ConfigError):
        config.set_value("report", "top_n", "banana")
    with pytest.raises(config.ConfigError):
        config.set_value("privacy", "redact_patterns", "(unclosed")


def test_redaction_builtin_and_user_patterns():
    text = ("token=ghp_abcdefghijklmnopqrstuvwxyz0123 "
            "postgres://u:hunter2@db/x ACME-12345")
    out = redact(text)
    assert "ghp_" not in out and "hunter2" not in out
    from tuner.security.redact import compile_extra
    assert "ACME" not in redact(text, compile_extra([r"ACME-\d+"]))


def test_safe_json_cannot_break_out_of_script_tag():
    out = safe_json({"x": "</script><script>alert(1)</script><!--"})
    assert "</script" not in out.lower() and "<!--" not in out
    assert json.loads(out)["x"].startswith("</script>")
