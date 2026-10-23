"""Aggregate raw usage rows into totals, per-model, and quality summaries."""

from __future__ import annotations

from collections import defaultdict

from tuner.collectors.cursor_estimate import KNOWN_GAPS

TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_write_tokens",
              "cache_read_tokens")
CONF_ORDER = {"low": 0, "medium": 1, "high": 2}


def total_of(d: dict) -> int:
    """Sum of the four disjoint token categories."""
    return sum(int(d.get(k) or 0) for k in TOKEN_KEYS)


def totals(rows: list[dict]) -> dict:
    """Token totals across rows (including a `total`)."""
    out = {k: sum(int(r.get(k) or 0) for r in rows) for k in TOKEN_KEYS}
    out["total"] = sum(out.values())
    out["calls"] = sum(int(r.get("calls") or 0) for r in rows)
    return out


def by_model(rows: list[dict]) -> list[dict]:
    """Per-model token breakdown with a combined measurement label."""
    groups: dict[str | None, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r.get("model")].append(r)
    out = []
    for model, rs in groups.items():
        q = quality(rs)
        out.append({"model": model, **totals(rs),
                    "measurement": q["measurement"],
                    "confidence": q["confidence"]})
    return sorted(out, key=lambda m: -m["total"])


def quality(rows: list[dict]) -> dict:
    """Measured/estimated status, weakest confidence, methods and gaps."""
    measured = sum(total_of(r) for r in rows
                   if r.get("measurement") == "measured")
    estimated = sum(total_of(r) for r in rows
                    if r.get("measurement") != "measured")
    if not rows or (measured == 0 and estimated == 0):
        label = "unavailable"
    elif estimated == 0:
        label = "measured"
    elif measured == 0:
        label = "estimated"
    else:
        label = "mixed"
    weighted = [r for r in rows if total_of(r) > 0] or rows
    conf = min((r.get("confidence", "low") for r in weighted),
               key=lambda c: CONF_ORDER.get(c, 0), default="low")
    methods = sorted({r["method"] for r in rows if r.get("method")})
    gaps = sorted({g for m in methods for g in KNOWN_GAPS.get(m, [])})
    return {"measurement": label, "confidence": conf,
            "measured_tokens": measured, "estimated_tokens": estimated,
            "estimate_methods": methods, "known_gaps": gaps,
            "sources": sorted({r["source"] for r in rows if r.get("source")})}


def cost_inputs(rows: list[dict]) -> list[dict]:
    """Per-model dicts (with measurement) suitable for estimate_cost."""
    out = []
    for m in by_model(rows):
        out.append({k: m[k] for k in ("model", "measurement",
                                      *TOKEN_KEYS)})
    return out
