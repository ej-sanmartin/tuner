"""Install/remove Tuner's Cursor hooks in `~/.cursor/hooks.json`.

Only entries carrying our marker argument are ever touched; every other
hook (and unknown top-level key) is preserved. If the file is not valid
JSON we refuse to modify it rather than risk destroying user config.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from tuner.collectors.cursor_paths import hooks_json_path
from tuner.fsutil import atomic_write_text
from tuner.hook_spool import EVENTS
from tuner.integrations.exe import tuner_command

MARKER = "--tuner-managed"


class HooksError(RuntimeError):
    """The hooks file could not be safely modified."""


def _load(path: Path) -> dict:
    """Read hooks.json (or an empty skeleton); raise on invalid JSON."""
    if not path.exists():
        return {"version": 1, "hooks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as exc:
        raise HooksError(f"{path} is not valid JSON; not modifying it "
                         f"({exc})") from exc
    if not isinstance(data, dict) or not isinstance(
            data.get("hooks", {}), dict):
        raise HooksError(f"{path} has an unexpected structure")
    data.setdefault("version", 1)
    data.setdefault("hooks", {})
    return data


def _is_ours(entry: object) -> bool:
    """True for hook entries Tuner installed."""
    return isinstance(entry, dict) and MARKER in str(entry.get("command"))


def installed_events(path: Path | None = None) -> list[str]:
    """Events that currently have a Tuner-managed hook."""
    try:
        data = _load(path or hooks_json_path())
    except HooksError:
        return []
    return [e for e, lst in data["hooks"].items()
            if isinstance(lst, list) and any(_is_ours(x) for x in lst)]


def install(path: Path | None = None) -> list[str]:
    """Idempotently register hooks; returns the events configured."""
    path = path or hooks_json_path()
    data = _load(path)
    if path.exists():
        backup = path.with_name(path.name + ".tuner-backup")
        if not backup.exists():
            shutil.copy2(path, backup)
    for event in EVENTS:
        entries = [x for x in data["hooks"].get(event, [])
                   if not _is_ours(x)]
        entries.append({"command": tuner_command("hook", event, MARKER),
                        "timeout": 5})
        data["hooks"][event] = entries
    atomic_write_text(path, json.dumps(data, indent=2) + "\n", private=False)
    return list(EVENTS)


def uninstall(path: Path | None = None) -> list[str]:
    """Remove only Tuner's hooks; returns the events cleaned."""
    path = path or hooks_json_path()
    if not path.exists():
        return []
    data = _load(path)
    cleaned = []
    for event in list(data["hooks"]):
        lst = data["hooks"][event]
        if not isinstance(lst, list):
            continue
        keep = [x for x in lst if not _is_ours(x)]
        if len(keep) != len(lst):
            cleaned.append(event)
            if keep:
                data["hooks"][event] = keep
            else:
                del data["hooks"][event]
    if cleaned:
        atomic_write_text(path, json.dumps(data, indent=2) + "\n",
                          private=False)
    return cleaned
