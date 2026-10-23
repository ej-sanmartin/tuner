"""Decide where a generated skill belongs (global vs project)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tuner import paths


class PlacementError(ValueError):
    """No safe destination could be determined."""


@dataclass(frozen=True)
class Placement:
    """Resolved destination for a skill."""

    scope: str  # global | project
    base_dir: Path  # skills root, e.g. ~/.claude/skills
    repo: str | None
    reason: str

    def skill_dir(self, name: str) -> Path:
        """Folder for skill `name` (name is validated by the caller)."""
        return self.base_dir / name


def decide(scope_pref: str, repos: list[str], repo_roots: dict[str, str],
           skill_dir: str) -> Placement:
    """Classify a finding into global or project placement.

    * Findings seen across >= 2 repositories -> global (reusable workflow).
    * Findings confined to one repository -> that repository's skills dir.
    * Explicit config/recommendation scope overrides the heuristic.
    """
    unique = sorted(set(repos))
    scope = scope_pref
    if scope == "auto":
        scope = "global" if len(unique) >= 2 else "project"
        reason = (f"seen in {len(unique)} repositories"
                  if scope == "global" else "confined to one repository")
        if not unique:
            scope, reason = "global", "no repository evidence; defaulting " \
                                      "to global"
    else:
        reason = f"scope set explicitly to {scope}"
    if scope == "global":
        return Placement("global", paths.user_home() / skill_dir, None,
                         reason)
    if len(unique) != 1:
        raise PlacementError("project scope needs exactly one repository "
                             f"(got {unique or 'none'})")
    root = repo_roots.get(unique[0])
    if not root:
        raise PlacementError(f"unknown project path for repo {unique[0]}")
    return Placement("project", Path(root) / skill_dir, unique[0], reason)


def inside(base: Path, target: Path) -> bool:
    """True if `target` resolves inside `base` (blocks path traversal)."""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False
