"""Render the self-contained, offline `report.html`.

The page is static HTML + CSS + JS with the report data embedded as JSON.
The JS builds the DOM exclusively through `textContent`, and the JSON is
escaped so no data can terminate the script element or inject markup. A
restrictive CSP blocks all network access.
"""

from __future__ import annotations

import json
from importlib import resources

# Concatenated in order into one script; report.js must come last.
JS_FILES = ("md.js", "task.js", "report.js")

_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026",
            "\u2028": "\\u2028", "\u2029": "\\u2029"}


def safe_json(obj: object) -> str:
    """JSON safe to embed inside a <script> element."""
    text = json.dumps(obj, ensure_ascii=True, separators=(",", ":"),
                      default=str)
    for char, repl in _ESCAPES.items():
        text = text.replace(char, repl)
    return text


def _asset(name: str) -> str:
    """Read a bundled template file."""
    ref = resources.files("tuner.reports") / "templates" / name
    return ref.read_text(encoding="utf-8")


def render_html(usage: dict, analysis: dict | None = None,
                skills: list[dict] | None = None) -> str:
    """Return the complete HTML document for the given report data."""
    page = _asset("report.html")
    page = page.replace("/*__CSS__*/", _asset("report.css"))
    script = "\n".join(_asset(n) for n in JS_FILES)
    page = page.replace("/*__JS__*/", script)
    data = {"usage": usage, "analysis": analysis, "skills": skills or []}
    return page.replace("/*__DATA__*/", safe_json(data))
