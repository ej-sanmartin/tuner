"""Shrink timeline items for the evidence bundle (not usage.json).

Absolute paths repeat on every item: each transcript `ref` carries the
full file path, and tool targets carry the home/repo prefix. Moving the
file paths to one `sources` map per task and abbreviating prefixes cuts
the bundle roughly in half without losing any citable id.
"""

from __future__ import annotations

from tuner import paths


def shorten(text: str | None, root: str | None) -> str | None:
    """Abbreviate repo root as $REPO and the home directory as ~."""
    if not text:
        return text
    if root:
        text = text.replace(root, "$REPO")
    return text.replace(str(paths.user_home()), "~")


def compact_timeline(items: list[dict], root: str | None
                     ) -> tuple[dict[str, str], list[dict]]:
    """Return ({alias: transcript path}, items without null fields).

    `ref` becomes "alias#Lnn"; targets/errors use short path prefixes.
    """
    sources: dict[str, str] = {}
    out: list[dict] = []
    for it in items:
        it.pop("full", None)  # report-only; evidence uses bounded excerpts
        it = {k: v for k, v in it.items() if v is not None}
        ref = it.get("ref")
        if ref:
            path, _, line = ref.partition("#")
            alias = sources.setdefault(
                path, f"f{len(sources)}") if path else ""
            it["ref"] = f"{alias}#{line}" if line else alias
        for key in ("target", "error"):
            if isinstance(it.get(key), str):
                it[key] = shorten(it[key], root)
        out.append(it)
    return {a: p for p, a in sources.items()}, out
