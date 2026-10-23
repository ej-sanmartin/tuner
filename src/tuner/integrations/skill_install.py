"""Install/remove the thin `/tuner` Agent Skill (managed by Tuner)."""

from __future__ import annotations

import shutil
from pathlib import Path

from tuner import paths
from tuner.fsutil import atomic_write_text
from tuner.skills import frontmatter

SKILL_NAME = "tuner"


def bundled_skill_dir() -> Path:
    """The skill shipped with Tuner (wheel or source checkout)."""
    here = Path(__file__).resolve()
    for cand in (here.parents[1] / "_agent_skills" / SKILL_NAME,
                 here.parents[3] / "agent-skills" / SKILL_NAME):
        if (cand / "SKILL.md").is_file():
            return cand
    raise FileNotFoundError("bundled tuner skill not found")


def bundled_text() -> str:
    """Contents of the bundled SKILL.md."""
    return (bundled_skill_dir() / "SKILL.md").read_text(encoding="utf-8")


def target_dir(skill_dir: str = ".claude/skills") -> Path:
    """Global install location (read by Cursor and Claude Code)."""
    return paths.user_home() / skill_dir / SKILL_NAME


def is_managed(directory: Path) -> bool:
    """True if the installed skill carries Tuner's managed marker."""
    try:
        parsed = frontmatter.parse((directory / "SKILL.md").read_text("utf-8"))
    except OSError:
        return False
    meta = (parsed[0].get("metadata") if parsed else None) or {}
    return isinstance(meta, dict) and meta.get("tuner-managed") == "true"


def install(skill_dir: str = ".claude/skills") -> Path:
    """Install or refresh the skill; never overwrite an unmanaged one."""
    dest = target_dir(skill_dir)
    if dest.exists() and not is_managed(dest):
        raise FileExistsError(f"{dest} exists and is not managed by Tuner")
    src = bundled_skill_dir()
    for f in src.rglob("*"):
        if f.is_file():
            out = dest / f.relative_to(src)
            text = f.read_text(encoding="utf-8")
            if f.name == "SKILL.md":
                from tuner import __version__
                text = frontmatter.set_managed(text, "install", __version__)
            atomic_write_text(out, text)
    return dest


def uninstall(skill_dir: str = ".claude/skills") -> bool:
    """Remove the skill only if Tuner manages it."""
    dest = target_dir(skill_dir)
    if dest.exists() and is_managed(dest):
        shutil.rmtree(dest)
        return True
    return False
