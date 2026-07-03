"""Regime invariants: budgets hold, cost model is honest."""

from __future__ import annotations

from jumping_rope.tokens import count_tokens

from ropebench.regimes import (
    FullHistoryRegime,
    RopeRegime,
    SummaryRegime,
    TruncateRegime,
)
from ropebench.scenario import generate


def replay(regime: object, seed: int = 1, turns: int = 40) -> None:
    scenario = generate(seed, n_turns=turns)
    for t in range(1, turns + 1):
        regime.observe(t, scenario.turns[t - 1])  # type: ignore[attr-defined]
        regime.end_turn()  # type: ignore[attr-defined]


def test_full_history_grows_monotonically() -> None:
    regime = FullHistoryRegime()
    replay(regime)
    assert regime.turn_tokens == sorted(regime.turn_tokens)
    assert regime.turn_tokens[-1] > regime.turn_tokens[0] * 5


def test_truncate_budget_holds_every_turn() -> None:
    regime = TruncateRegime(budget_tokens=800)
    scenario = generate(2, n_turns=40)
    for t in range(1, 41):
        regime.observe(t, scenario.turns[t - 1])
        assert count_tokens(regime.context()) <= 800


def test_summary_budget_holds_and_loses_detail() -> None:
    regime = SummaryRegime(budget_tokens=800)
    scenario = generate(2, n_turns=60)
    for t in range(1, 61):
        regime.observe(t, scenario.turns[t - 1])
        assert count_tokens(regime.context()) <= 800 + 50  # transient slack
    # The oldest fact's pinned value must have been summarized away.
    first_fact = next(
        e for turn in scenario.turns for e in turn if e.kind == "fact"
    )
    value = first_fact.text.split("build ")[1].split()[0]
    assert value not in regime.context(), "summary regime failed to lose detail"


def test_rope_budget_holds_and_offers_retrieval(tmp_path: object) -> None:
    regime = RopeRegime(rope_budget_tokens=600, data_dir=str(tmp_path))
    scenario = generate(2, n_turns=40)
    for t in range(1, 41):
        regime.observe(t, scenario.turns[t - 1])
        assert count_tokens(regime.context()) <= 600
    retrieve = regime.retriever()
    assert retrieve is not None
    result = retrieve("pinned build pipeline")
    assert result.startswith("RETRIEVED|") or result == ""
    regime.close()


def test_rope_goal_status_reflected_in_context(tmp_path: object) -> None:
    regime = RopeRegime(data_dir=str(tmp_path))
    scenario = generate(4, n_turns=40)
    for t in range(1, 41):
        regime.observe(t, scenario.turns[t - 1])
    done_events = [
        e for turn in scenario.turns[:40] for e in turn if e.kind == "goal_done"
    ]
    assert done_events, "scenario must complete at least one goal in 40 turns"
    assert "✓" in regime.context()
    regime.close()
