"""Cursor on-disk locations and project-slug decoding."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from tuner import paths


def cursor_home() -> Path:
    """`~/.cursor` (same relative location on macOS/Windows/Linux)."""
    return paths.user_home() / ".cursor"


def projects_dir() -> Path:
    """Directory containing one folder per workspace slug."""
    return cursor_home() / "projects"


def state_db_path() -> Path:
    """Cursor's internal global state DB (undocumented, read-only use)."""
    home = paths.user_home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or home / "AppData/Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return base / "Cursor" / "User" / "globalStorage" / "state.vscdb"


def tracking_db_path() -> Path:
    """Cursor's AI code-tracking DB (model per conversation, summaries)."""
    return cursor_home() / "ai-tracking" / "ai-code-tracking.db"


def hooks_json_path() -> Path:
    """User-level Cursor hooks configuration file."""
    return cursor_home() / "hooks.json"


def _slugify(name: str) -> str:
    """Cursor's slug rule: non-alphanumerics become '-'."""
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")


def decode_slug(slug: str) -> str | None:
    """Recover a workspace path from a project slug by walking the disk.

    Slugs are lossy ('.', '/', '_' all become '-'), so we match directory
    entries whose slug equals a prefix of the remaining text. Returns None
    when the path no longer exists or is ambiguous.
    """
    roots = [Path("/")] if sys.platform != "win32" else [
        Path(f"{c}:/") for c in "CDEFGHIJKLMNOPQRSTUVWXYZ"
        if slug.lower().startswith(f"{c.lower()}-")]
    if sys.platform == "win32" and roots:
        slug = slug[2:]
    for root in roots:
        found = _walk(root, slug)
        if found:
            return str(found)
    return None


def _walk(cur: Path, rest: str) -> Path | None:
    """Depth-first match of `rest` against child directory slugs."""
    if not rest:
        return cur
    try:
        children = [c for c in cur.iterdir() if c.is_dir()]
    except OSError:
        return None
    for child in sorted(children, key=lambda c: -len(c.name)):
        s = _slugify(child.name)
        if not s:
            continue
        if rest == s:
            return child
        if rest.startswith(s + "-"):
            hit = _walk(child, rest[len(s) + 1:])
            if hit:
                return hit
    return None
