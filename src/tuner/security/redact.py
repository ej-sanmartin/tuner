"""Best-effort secret redaction applied before anything is stored,
exported, or shown to a model. Redaction is defence in depth, not a
guarantee: Tuner also avoids storing raw prompts or file contents."""

from __future__ import annotations

import re
from collections.abc import Iterable

MASK = "[REDACTED]"

_BUILTIN = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE"
    r" KEY-----|$)",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bASIA[0-9A-Z]{16}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
    r"\bsk-[A-Za-z0-9_-]{16,}\b",
    r"\bAIza[0-9A-Za-z_-]{30,}\b",
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}",
]
_BUILTIN_RE = [re.compile(p) for p in _BUILTIN]

_AUTH_HEADER = re.compile(
    r"(?i)\b(authorization|x-api-key|proxy-authorization)\s*[:=]\s*[^\s'\"]+"
    r"(?:\s+[^\s'\"]+)?")
_ASSIGN = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]*(?:secret|token|passw(?:or)?d|api[_-]?key|"
    r"private[_-]?key|credential|auth)[A-Za-z0-9_.-]*)\s*([:=])\s*"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;]+)")
_URL_CRED = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@")


def compile_extra(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    """Compile user-supplied redaction regexes (validated by config)."""
    return [re.compile(p) for p in patterns]


def redact(text: str, extra: Iterable[re.Pattern[str]] = ()) -> str:
    """Return `text` with common secret formats masked."""
    if not text:
        return text
    text = _URL_CRED.sub(lambda m: f"{m.group(1)}{MASK}@", text)
    text = _AUTH_HEADER.sub(lambda m: f"{m.group(1)}: {MASK}", text)
    for rx in _BUILTIN_RE:
        text = rx.sub(MASK, text)
    text = _ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)} {MASK}", text)
    for rx in extra:
        text = rx.sub(MASK, text)
    return text


def preview(text: str, limit: int = 200,
            extra: Iterable[re.Pattern[str]] = ()) -> str:
    """Whitespace-collapsed, redacted, truncated one-line preview."""
    flat = " ".join((text or "").split())
    flat = redact(flat, extra)
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
