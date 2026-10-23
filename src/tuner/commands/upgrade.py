"""`tuner upgrade`: update Tuner, then refresh what it installed."""

from __future__ import annotations

import importlib.metadata as md
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from tuner import __version__
from tuner.commands.common import TunerError, load_config
from tuner.integrations.exe import tuner_argv
from tuner.integrations.sync import sync

PACKAGE = "agent-tuner"


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("upgrade", help="upgrade Tuner and refresh hooks, "
                       "skill, and schedule")
    p.add_argument("--sync-only", action="store_true",
                   help="skip the package upgrade; just refresh installed "
                   "integrations (use after any manual upgrade)")
    p.set_defaults(func=run)


def install_method() -> tuple[str, str]:
    """Classify how Tuner is installed: (kind, detail)."""
    try:
        raw = md.distribution(PACKAGE).read_text("direct_url.json")
        info = json.loads(raw) if raw else {}
    except (md.PackageNotFoundError, ValueError):
        info = {}
    prefix = Path(sys.prefix).as_posix().lower()
    tool_dir = os.environ.get("UV_TOOL_DIR", "")
    uv_tool = "/uv/tools/" in prefix or (
        tool_dir and prefix.startswith(Path(tool_dir).as_posix().lower()))
    if "dir_info" in info:  # installed from a local checkout
        src = unquote(urlparse(info["url"]).path)
        if sys.platform == "win32":
            src = src.lstrip("/")
        kind = "editable" if info["dir_info"].get("editable") else "path"
        return (f"{kind}-uv" if uv_tool else kind), src
    if uv_tool:
        return "uv-tool", prefix
    if "/pipx/venvs/" in prefix:
        return "pipx", prefix
    return "other", prefix


def _run(cmd: list[str]) -> None:
    """Run a command, streaming its output; raise TunerError on failure."""
    print("+ " + " ".join(cmd))
    if subprocess.run(cmd, check=False).returncode != 0:  # noqa: S603
        raise TunerError(f"command failed: {' '.join(cmd)}")


def _need(exe: str) -> str:
    """Absolute path of a required tool."""
    found = shutil.which(exe)
    if not found:
        raise TunerError(f"`{exe}` not found on PATH; install it or "
                         "upgrade manually, then run "
                         "`tuner upgrade --sync-only`")
    return found


def upgrade_package(kind: str, detail: str) -> None:
    """Upgrade the package using the tool that installed it."""
    if sys.platform == "win32" and kind == "uv-tool":
        raise TunerError(
            "Windows locks the running tuner.exe. Run these two commands:\n"
            f"  uv tool upgrade {PACKAGE}\n  tuner upgrade --sync-only")
    if kind == "uv-tool":
        _run([_need("uv"), "tool", "upgrade", PACKAGE])
    elif kind == "pipx":
        _run([_need("pipx"), "upgrade", PACKAGE])
    elif kind.startswith(("editable", "path")):
        _run([_need("git"), "-C", detail, "pull", "--ff-only"])
        if kind.endswith("-uv"):
            flags = ["--editable"] if kind.startswith("editable") else []
            _run([_need("uv"), "tool", "install", "--force", "--reinstall",
                  *flags, detail])
    else:
        raise TunerError(f"unknown install method; run: pip install -U "
                         f"{PACKAGE}, then `tuner upgrade --sync-only`")


def run(args) -> int:
    """Upgrade (unless --sync-only), then refresh via the new code."""
    if args.sync_only:
        cfg = load_config()
        for name, result in sync(cfg):
            print(f"  ok    {name}: {result}")
        print(f"Tuner {__version__} is in sync.")
        return 0
    kind, detail = install_method()
    print(f"Tuner {__version__} ({kind})")
    upgrade_package(kind, detail)
    # Re-run in the *new* code: this process still has the old modules.
    new = subprocess.run([*tuner_argv(), "--version"], capture_output=True,
                         text=True, check=False).stdout.strip()
    print(new or "installed version unknown")
    _run([*tuner_argv(), "upgrade", "--sync-only"])
    return 0
