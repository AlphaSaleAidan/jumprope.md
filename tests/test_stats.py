"""Hermetic unit tests for the paired-bootstrap statistics (S1).

Known-answer cases computed by hand, plus determinism and CI-direction checks.
"""

from __future__ import annotations

import pytest

from ropebench.stats import (
    VERDICT_BETTER,
    VERDICT_PARITY,
    VERDICT_WORSE,
    _percentile,
    paired_bootstrap,
)


def test_percentile_known_values() -> None:
    vals = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert _percentile(vals, 0.0) == 0.0
    assert _percentile(vals, 1.0) == 4.0
    assert _percentile(vals, 0.5) == 2.0
    assert _percentile(vals, 0.25) == 1.0


def test_point_estimates_are_exact() -> None:
    # A hits 4/5, B hits 2/5 → diff = +0.4, wins/losses/ties countable by hand.
    a = [1, 1, 1, 1, 0]
    b = [1, 0, 0, 1, 0]
    r = paired_bootstrap(a, b, resamples=2000, seed=1)
    assert r.n == 5
    assert r.mean_a == pytest.approx(0.8)
    assert r.mean_b == pytest.approx(0.4)
    assert r.diff == pytest.approx(0.4)
    # per-probe: (1-1)=0 tie, (1-0)=win, (1-0)=win, (1-1)=0 tie, (0-0)=0 tie
    assert r.wins == 2
    assert r.losses == 0
    assert r.ties == 3


def test_identical_conditions_are_parity_with_zero_ci() -> None:
    a = [1, 0, 1, 0, 1, 1, 0, 0]
    r = paired_bootstrap(a, list(a), resamples=2000, seed=3)
    assert r.diff == 0.0
    assert r.ci_low == 0.0 and r.ci_high == 0.0
    assert r.verdict == VERDICT_PARITY


def test_total_domination_gives_better_verdict_ci_clears_zero() -> None:
    a = [1] * 40
    b = [0] * 40
    r = paired_bootstrap(a, b, resamples=5000, seed=7)
    assert r.diff == 1.0
    assert r.ci_low > 0  # every resample is +1.0
    assert r.verdict == VERDICT_BETTER


def test_reverse_domination_gives_worse_verdict() -> None:
    r = paired_bootstrap([0] * 30, [1] * 30, resamples=3000, seed=9)
    assert r.verdict == VERDICT_WORSE
    assert r.ci_high < 0


def test_tiny_edge_on_small_n_is_parity_ci_spans_zero() -> None:
    # A net one-probe advantage with real disagreement in both directions
    # (2 wins, 1 loss) on n=8 — the retrospective's fragile Opus case. The
    # CI must span zero, so the claim is written as parity, not superiority.
    a = [1, 1, 1, 1, 1, 0, 0, 0]  # 5/8
    b = [1, 1, 1, 0, 0, 1, 0, 0]  # 4/8, disagrees both ways
    r = paired_bootstrap(a, b, resamples=5000, seed=11)
    assert r.diff == pytest.approx(0.125)
    assert r.wins == 2 and r.losses == 1
    assert r.ci_low < 0 < r.ci_high, "a one-probe edge must not read as significant"
    assert r.verdict == VERDICT_PARITY


def test_determinism_same_seed_same_ci() -> None:
    a = [1, 0, 1, 1, 0, 1, 0, 0, 1, 1]
    b = [0, 0, 1, 0, 0, 1, 0, 0, 1, 0]
    r1 = paired_bootstrap(a, b, resamples=4000, seed=42)
    r2 = paired_bootstrap(a, b, resamples=4000, seed=42)
    assert (r1.ci_low, r1.ci_high) == (r2.ci_low, r2.ci_high)


def test_claim_phrase_respects_verdict() -> None:
    better = paired_bootstrap([1] * 40, [0] * 40, resamples=2000, seed=1)
    assert "beats" in better.claim_phrase("rope", "carry-all")
    parity = paired_bootstrap([1, 0, 1, 0], [1, 0, 1, 0], resamples=2000, seed=1)
    phrase = parity.claim_phrase("rope", "carry-all")
    assert "parity" in phrase and "not distinguishable" in phrase


def test_rejects_malformed_input() -> None:
    with pytest.raises(ValueError):
        paired_bootstrap([1, 0], [1], resamples=100)
    with pytest.raises(ValueError):
        paired_bootstrap([], [], resamples=100)
    with pytest.raises(ValueError):
        paired_bootstrap([2, 0], [1, 0], resamples=100)
