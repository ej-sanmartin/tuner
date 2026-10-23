"""Minimal SKILL.md frontmatter parser/serialiser (no YAML dependency).

Supports what Agent Skills need: flat `key: value` scalars, a `metadata:`
map of string values, and simple `- item` lists. Anything fancier is left
untouched when we only read; we only *write* files we generate.
"""

from __future__ import annotations

import re

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.S)


_NEEDS_QUOTE = re.compile(r"[:#\n\"'\[\]{}&*!|>%@`]|^\s|\s$|^[-?]")


_AMBIGUOUS = re.compile(r"(?i)true|false|null|yes|no|on|off|~|[-+]?[\d.]+")


def _scalar(raw: str) -> str:
    """Unquote a YAML scalar."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        inner = raw[1:-1]
        return inner.replace('\\"', '"') if raw[0] == '"' else inner
    return raw


def parse(text: str) -> tuple[dict, str] | None:
    """Return (frontmatter dict, body) or None if there is no frontmatter."""
    m = _FM.match(text)
    if not m:
        return None
    data: dict = {}
    current: str | None = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) and current:
            stripped = line.strip()
            if stripped.startswith("- "):
                data[current] = (data[current] if isinstance(
                    data[current], list) else []) + [_scalar(stripped[2:])]
            elif ":" in stripped:
                k, _, v = stripped.partition(":")
                if not isinstance(data[current], dict):
                    data[current] = {}
                data[current][k.strip()] = _scalar(v)
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        current = key.strip()
        data[current] = _scalar(value) if value.strip() else ""
    return data, m.group(2)


def _quote(value: str) -> str:
    """Quote a scalar when it could confuse a YAML reader."""
    if value == "" or _NEEDS_QUOTE.search(value) or _AMBIGUOUS.fullmatch(
            value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def dump(data: dict, body: str) -> str:
    """Serialise frontmatter (scalars, lists, string maps) plus body."""
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            lines += [f"  {k}: {_quote(str(v))}" for k, v in value.items()]
        elif isinstance(value, list):
            lines.append(f"{key}:")
            lines += [f"  - {_quote(str(v))}" for v in value]
        else:
            lines.append(f"{key}: {_quote(str(value))}")
    lines += ["---", ""]
    return "\n".join(lines) + "\n" + body.lstrip("\n")


def set_managed(text: str, change_id: str, version: str) -> str:
    """Return `text` with Tuner's managed-by metadata inserted."""
    parsed = parse(text)
    if parsed is None:
        return text
    data, body = parsed
    meta = dict(data.get("metadata") or {}) if isinstance(
        data.get("metadata"), dict) else {}
    meta.update({"tuner-managed": "true", "tuner-change": change_id,
                 "tuner-version": version})
    data["metadata"] = meta
    return dump(data, body)
