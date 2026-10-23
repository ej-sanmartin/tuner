"""Deterministic pricing and cost math."""

from tuner.pricing import PriceBook, estimate_cost
from tuner.pricing.cost import compute_cost
from tuner.pricing.table import Rate, normalize


def tokens(i=0, o=0, cw=0, cr=0, model="claude-sonnet-4-5"):
    return {"model": model, "input_tokens": i, "output_tokens": o,
            "cache_write_tokens": cw, "cache_read_tokens": cr,
            "measurement": "measured"}


def test_cost_is_weighted_sum_of_disjoint_categories():
    rate = Rate("m", "p", 3.0, 15.0, 3.75, 0.30, "t")
    usd, missing = compute_cost({"input_tokens": 1_000_000,
                                 "output_tokens": 1_000_000,
                                 "cache_write_tokens": 1_000_000,
                                 "cache_read_tokens": 1_000_000}, rate)
    assert round(usd, 4) == 22.05 and missing == []


def test_unknown_model_gives_incomplete_estimate_not_a_guess(env):
    est = estimate_cost([tokens(100, 100, model="mystery-model-9")],
                        PriceBook(), None)
    assert est["complete"] is False and est["usd"] == 0
    assert est["by_model"][0]["status"] == "unknown_model"
    assert est["confidence"] == "low"


def test_model_name_normalisation_handles_dates_and_suffixes():
    keys = normalize("claude-sonnet-4-5-20250929-thinking-high")
    assert "claude-sonnet-4-5" in keys


def test_dated_override_wins_by_effective_date(env):
    from tuner import paths
    paths.ensure_private_dir(paths.config_dir())
    (paths.config_dir() / "pricing_overrides.toml").write_text(
        '[[model]]\nid="claude-sonnet-4-5"\nprovider="anthropic"\n'
        'input=1.0\noutput=2.0\neffective_from="2026-01-01"\n'
        '[[model]]\nid="claude-sonnet-4-5"\nprovider="anthropic"\n'
        'input=9.0\noutput=9.0\neffective_from="2026-06-01"\n',
        encoding="utf-8")
    book = PriceBook()
    assert book.lookup("claude-sonnet-4-5", "2026-03-01").input == 1.0
    assert book.lookup("claude-sonnet-4-5", "2026-07-01").input == 9.0
    est = estimate_cost([tokens(1_000_000)], book, "2026-03-01")
    assert est["usd"] == 1.0 and est["by_model"][0]["price_basis"] == \
        "dated_override"


def test_estimated_tokens_downgrade_cost_confidence(env):
    row = tokens(1000, 1000)
    row["measurement"] = "estimated"
    est = estimate_cost([row], PriceBook(), None)
    assert est["confidence"] in ("medium", "low")
    assert any("estimated" in x for x in est["limitations"])
