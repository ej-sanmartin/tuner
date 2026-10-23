"""Convert LiteLLM's community pricing file (MIT) into Tuner's format.

Source: https://github.com/BerriAI/litellm (model_prices_and_context_window
_backup.json). LiteLLM carries no effective dates, so rates derived from
it are always labelled "current rates". Network access happens only when
the user runs `tuner pricing refresh`.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from typing import Any

SOURCE_URL = ("https://raw.githubusercontent.com/BerriAI/litellm/main/litellm/"
              "model_prices_and_context_window_backup.json")
PROVIDERS = {"anthropic", "openai", "xai", "gemini", "deepseek", "mistral"}
PER_M = 1_000_000


def fetch(url: str = SOURCE_URL, timeout: int = 20) -> dict[str, Any]:
    """Download the raw LiteLLM table (explicit user action only)."""
    req = urllib.request.Request(url, headers={"User-Agent": "tuner"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.load(resp)


def _per_million(value: Any) -> float | None:
    """USD/token -> USD per million tokens (None when absent)."""
    if isinstance(value, (int, float)) and value >= 0:
        return round(value * PER_M, 6)
    return None


def convert(raw: dict[str, Any], fetched_at: datetime | None = None
            ) -> dict[str, Any]:
    """Filter and convert raw LiteLLM data to the bundled schema."""
    models: dict[str, Any] = {}
    for key, v in raw.items():
        if not isinstance(v, dict) or key == "sample_spec":
            continue
        prov = v.get("litellm_provider")
        if prov not in PROVIDERS or v.get("mode") != "chat":
            continue
        if "/" in key:  # accept only "<provider>/<model>" for this provider
            prefix, _, key = key.partition("/")
            if prefix != prov or "/" in key or key in models:
                continue
        rate = {
            "provider": prov,
            "input": _per_million(v.get("input_cost_per_token")),
            "output": _per_million(v.get("output_cost_per_token")),
            "cache_write": _per_million(
                v.get("cache_creation_input_token_cost")),
            "cache_read": _per_million(v.get("cache_read_input_token_cost")),
            "tiered": any(k.endswith("above_200k_tokens") for k in v),
        }
        if rate["input"] is not None and rate["output"] is not None:
            models[key] = rate
    when = (fetched_at or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "_meta": {
            "source": SOURCE_URL, "license": "MIT (BerriAI/litellm)",
            "fetched_at": when, "unit": "USD per 1M tokens",
            "effective_date": None,
            "note": "Current list prices; no historical effective dates.",
        },
        "models": models,
    }
