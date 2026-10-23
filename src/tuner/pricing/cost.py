"""Deterministic API-equivalent cost calculation.

Token categories in Tuner's data model are *disjoint* (input excludes
cached tokens; collectors normalise provider differences), so the cost is
a plain weighted sum. The result is an API-equivalent estimate, NOT actual
billing: subscription users are not charged these prices. A missing rate
produces an explicitly incomplete estimate; nothing is ever guessed.
"""

from __future__ import annotations

from tuner.pricing.table import PriceBook, Rate

PER_M = 1_000_000


def compute_cost(tokens: dict[str, int], rate: Rate) -> tuple[float, list[str]]:
    """Return (usd, missing_components) for one model's token counts."""
    parts = (
        ("input_tokens", rate.input), ("output_tokens", rate.output),
        ("cache_write_tokens", rate.cache_write),
        ("cache_read_tokens", rate.cache_read),
    )
    total, missing = 0.0, []
    for key, price in parts:
        count = int(tokens.get(key) or 0)
        if not count:
            continue
        if price is None:
            missing.append(key)
            continue
        total += count * price
    return total / PER_M, missing


def estimate_cost(by_model: list[dict], book: PriceBook,
                  day: str | None) -> dict:
    """Cost estimate for per-model token dicts.

    Each input dict needs `model`, the four token fields, and may carry
    `measurement`. Output states completeness and limitations.
    """
    lines, usd, incomplete, limits = [], 0.0, False, set()
    for m in by_model:
        rate = book.lookup(m.get("model"), day)
        line = {"model": m.get("model"),
                "tokens": {k: int(m.get(k) or 0) for k in (
                    "input_tokens", "output_tokens", "cache_write_tokens",
                    "cache_read_tokens")},
                "token_measurement": m.get("measurement", "unknown")}
        if rate is None:
            line.update(status="unknown_model", usd=None)
            incomplete = True
        else:
            cost, missing = compute_cost(line["tokens"], rate)
            status = "partial" if missing else "ok"
            line.update(
                status=status, usd=round(cost, 6), missing_rates=missing,
                provider=rate.provider, pricing_source=rate.source,
                price_basis=rate.basis, effective_from=rate.effective_from,
                rates_per_million={
                    "input": rate.input, "output": rate.output,
                    "cache_write": rate.cache_write,
                    "cache_read": rate.cache_read})
            usd += cost
            incomplete = incomplete or bool(missing)
            if rate.basis != "dated_override":
                limits.add("current list prices applied to historical "
                           "usage (no effective dates available)")
            if rate.tiered:
                limits.add("model has long-context tiered pricing that is "
                           "not modelled")
        if m.get("measurement") != "measured":
            limits.add("token counts are estimated, so cost is too")
        lines.append(line)
    limits.add("API-equivalent estimate; not actual billing or "
               "subscription spend")
    return {
        "usd": round(usd, 4),
        "complete": not incomplete,
        "confidence": "low" if incomplete else (
            "medium" if limits - {"API-equivalent estimate; not actual "
                                  "billing or subscription spend"}
            else "high"),
        "by_model": lines,
        "limitations": sorted(limits),
    }
