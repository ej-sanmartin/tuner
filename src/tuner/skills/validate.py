"""Validate generated skill content before it can be applied.

Generated text is derived from untrusted transcripts, so besides the
Agent Skills format we reject secrets and instructions that try to weaken
Tuner's or the agent's safety policies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tuner.security.redact import MASK, redact
from tuner.skills import frontmatter
from tuner.skills.discover import SkillInfo

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_LINES, MAX_BYTES = 500, 20_000
_RISKY = [
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
    r"disregard (the )?(system|safety|tuner)",
    r"disable (the )?(tuner|safety|permission|policy)",
    r"(curl|wget)[^\n|]*\|\s*(ba)?sh",
    r"\brm\s+-rf\s+[/~]",
    r"(exfiltrate|upload) (the )?(transcripts?|secrets?|credentials?)",
]
_RISKY_RE = [re.compile(p, re.I) for p in _RISKY]


@dataclass
class Validation:
    """Outcome of validating a skill."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no blocking errors were found."""
        return not self.errors


def _tokens(text: str) -> set[str]:
    """Lowercase word set for overlap estimation."""
    return {w for w in re.findall(r"[a-z]{4,}", text.lower())}


def validate_skill(name: str, text: str,
                   existing: list[SkillInfo] | None = None) -> Validation:
    """Check format, size, secrets, risky instructions, and overlap."""
    v = Validation()
    if not NAME_RE.match(name) or len(name) > 64:
        v.errors.append("name must be lowercase letters/digits/hyphens, "
                        "<= 64 chars, no leading/trailing/double hyphen")
    parsed = frontmatter.parse(text)
    if parsed is None:
        v.errors.append("missing YAML frontmatter")
        return v
    data, body = parsed
    if data.get("name") != name:
        v.errors.append("frontmatter name must equal the folder name")
    desc = str(data.get("description", "")).strip()
    if not desc or len(desc) > 1024:
        v.errors.append("description must be 1-1024 characters")
    if not body.strip():
        v.errors.append("body is empty")
    if text.count("\n") + 1 > MAX_LINES:
        v.errors.append(f"skill exceeds {MAX_LINES} lines; move detail to "
                        "references/")
    if len(text.encode()) > MAX_BYTES:
        v.errors.append(f"skill exceeds {MAX_BYTES} bytes")
    if redact(text) != text or MASK in text:
        v.errors.append("content appears to contain a secret or credential")
    for rx in _RISKY_RE:
        if rx.search(text):
            v.errors.append(f"risky instruction pattern: {rx.pattern}")
    mine = _tokens(desc)
    for other in existing or []:
        if other.name == name or not other.description:
            continue
        theirs = _tokens(other.description)
        union = mine | theirs
        if union and len(mine & theirs) / len(union) >= 0.5:
            v.warnings.append(f"description overlaps with existing skill "
                              f"'{other.name}' ({other.scope}); consider "
                              "updating it instead")
    return v
