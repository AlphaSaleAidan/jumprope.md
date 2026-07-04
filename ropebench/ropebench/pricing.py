"""Cost estimation and the budget guard (S0).

A paid sweep must never run blind. We take exact payload token counts from a
free scripted dry-run, multiply by published per-token input prices, print the
estimate, and abort if it exceeds ``JROPE_BENCH_BUDGET_USD``. Output tokens are
small and bounded (one short answer per probe) so input tokens dominate the
estimate; a fixed output allowance is added per call to stay conservative.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Published input $/1M tokens, matched by model-id substring (longest wins).
# Update as prices change — this table is the single source for estimates.
INPUT_PRICE_PER_MTOK: dict[str, float] = {
    "haiku": 1.00,
    "sonnet": 3.00,
    "opus": 15.00,
    "gpt-4o-mini": 0.15,
    "gpt-4o": 2.50,
    "deepseek": 0.28,
    "llama": 0.10,
}
_OUTPUT_ALLOWANCE_TOKENS = 80  # generous per-answer output budget


class BudgetExceeded(RuntimeError):
    """Raised at preflight when the estimate exceeds the configured budget."""


@dataclass(frozen=True)
class CostEstimate:
    model: str
    input_tokens: int
    calls: int
    price_per_mtok: float
    usd: float

    def render(self) -> str:
        return (
            f"cost estimate · model={self.model} · calls={self.calls} · "
            f"input≈{self.input_tokens:,} tok @ ${self.price_per_mtok:.2f}/Mtok "
            f"→ ${self.usd:.2f}"
        )


def price_for(model: str) -> float:
    matches = [(k, v) for k, v in INPUT_PRICE_PER_MTOK.items() if k in model.lower()]
    if not matches:
        raise KeyError(
            f"no price for model {model!r}; add it to INPUT_PRICE_PER_MTOK"
        )
    return max(matches, key=lambda kv: len(kv[0]))[1]


def estimate_cost(model: str, input_tokens: int, calls: int) -> CostEstimate:
    price = price_for(model)
    billable = input_tokens + calls * _OUTPUT_ALLOWANCE_TOKENS
    usd = billable / 1_000_000 * price
    return CostEstimate(
        model=model, input_tokens=input_tokens, calls=calls,
        price_per_mtok=price, usd=round(usd, 4),
    )


def budget_usd() -> float | None:
    raw = os.environ.get("JROPE_BENCH_BUDGET_USD")
    return None if raw is None else float(raw)


def enforce_budget(estimate: CostEstimate) -> None:
    """Print the estimate; abort if unset or over budget (S0)."""
    print(estimate.render())
    budget = budget_usd()
    if budget is None:
        raise BudgetExceeded(
            "JROPE_BENCH_BUDGET_USD is not set — refusing to run a paid sweep. "
            f"Set it to at least ${estimate.usd:.2f} to proceed."
        )
    if estimate.usd > budget:
        raise BudgetExceeded(
            f"estimate ${estimate.usd:.2f} exceeds budget ${budget:.2f}"
        )
    print(f"within budget (${budget:.2f}) — proceeding")
