"""Hermetic tests for the cost estimate + budget guard (S0)."""

from __future__ import annotations

import pytest

from ropebench.pricing import (
    BudgetExceeded,
    enforce_budget,
    estimate_cost,
    price_for,
)


def test_price_lookup_longest_match() -> None:
    assert price_for("claude-haiku-4-5") == 1.00
    assert price_for("anthropic/claude-opus-4-8") == 15.00
    with pytest.raises(KeyError):
        price_for("some-unknown-model")


def test_estimate_is_input_plus_output_allowance() -> None:
    e = estimate_cost("haiku", input_tokens=1_000_000, calls=100)
    # 1M input + 100*80 output allowance = 1,008,000 tok @ $1/Mtok
    assert e.usd == pytest.approx(1.008, abs=1e-3)
    assert "haiku" in e.render() and "$1.01" in e.render()


def test_budget_unset_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JROPE_BENCH_BUDGET_USD", raising=False)
    with pytest.raises(BudgetExceeded, match="not set"):
        enforce_budget(estimate_cost("haiku", 10_000, 10))


def test_budget_over_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JROPE_BENCH_BUDGET_USD", "0.01")
    with pytest.raises(BudgetExceeded, match="exceeds budget"):
        enforce_budget(estimate_cost("opus", 1_000_000, 100))


def test_budget_within_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JROPE_BENCH_BUDGET_USD", "100")
    enforce_budget(estimate_cost("haiku", 10_000, 10))  # no raise
