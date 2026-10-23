"""Locate the command that re-invokes Tuner (for hooks and schedulers)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def tuner_argv() -> list[str]:
    """argv prefix that runs this Tuner install (absolute paths)."""
    found = shutil.which("tuner")
    if found:
        return [str(Path(found).resolve())]
    argv0 = Path(sys.argv[0])
    if argv0.stem.lower().startswith("tuner") and argv0.exists():
        return [str(argv0.resolve())]
    return [sys.executable, "-m", "tuner"]


def quote(arg: str) -> str:
    """Quote an argument for both POSIX shells and Windows cmd/PowerShell."""
    if arg and not any(c in arg for c in ' \t"\'()&;|<>$`'):
        return arg
    return '"' + arg.replace('"', '\\"') + '"'


def tuner_command(*args: str) -> str:
    """Single command-line string invoking Tuner with `args`."""
    return " ".join(quote(a) for a in [*tuner_argv(), *args])
