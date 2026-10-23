"""Deterministic analysis cache key.

Any change to an input that can alter an analysis changes the key, so a
cached analysis is reused only when it is provably still applicable.
"""

from __future__ import annotations

from tuner.analysis import INSTRUCTIONS_VERSION
from tuner.config import Config
from tuner.fsutil import canonical_json, sha256_text
from tuner.integrations import skill_install
from tuner.pricing.table import overrides_file


def skill_instructions_hash() -> str:
    """Hash of the bundled /tuner skill text (the analysis instructions)."""
    try:
        text = skill_install.bundled_text()
    except OSError:
        text = ""
    return sha256_text(text)[:16]


def pricing_version(usage: dict) -> str:
    """Identify the pricing inputs (snapshot meta + user overrides)."""
    try:
        overrides = sha256_text(overrides_file().read_text("utf-8"))[:12]
    except OSError:
        overrides = "none"
    meta = usage.get("pricing", {}).get("meta", {})
    return sha256_text(canonical_json({"meta": meta,
                                       "overrides": overrides}))[:16]


def task_selection(usage: dict, top_n: int | None,
                   task_ids: list[str] | None) -> list[str]:
    """Ordered task ids to analyse (explicit ids, else top-N by tokens)."""
    ranked = [t["id"] for t in usage["tasks"]]
    if task_ids:
        return [t for t in task_ids if t in ranked]
    return ranked[:top_n or usage["selection"]["top_n"]]


def cache_key(snapshot_hash: str, selection: list[str], usage: dict,
              cfg: Config) -> str:
    """Key over snapshot, selection, instructions, pricing, and config."""
    material = {
        "snapshot": snapshot_hash,
        "tasks": selection,
        "instructions": [INSTRUCTIONS_VERSION, skill_instructions_hash()],
        "pricing": pricing_version(usage),
        "config": {"cost_estimation": cfg.analysis.cost_estimation,
                   "skills_mode": cfg.skills.mode,
                   "skills_scope": cfg.skills.scope,
                   "skill_dir": cfg.skills.skill_dir,
                   "redact": sorted(cfg.privacy.redact_patterns)},
    }
    return sha256_text(canonical_json(material))
