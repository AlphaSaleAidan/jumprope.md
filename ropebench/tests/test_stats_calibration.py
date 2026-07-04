"""Bootstrap CI coverage calibration — validates the stats machinery at scale.

The paired bootstrap CI must contain the true difference ~95% of the time. A
moderate run in CI (default tier) plus the full 20k run under @pytest.mark.local.
"""

from __future__ import annotations

import random

import pytest

from ropebench.stats import paired_bootstrap


def _coverage(trials: int, resamples: int) -> float:
    rng = random.Random(0)
    p_a, p_b, n, true_diff = 0.80, 0.60, 40, 0.20
    covered = 0
    for i in range(trials):
        a = [1 if rng.random() < p_a else 0 for _ in range(n)]
        b = [1 if rng.random() < p_b else 0 for _ in range(n)]
        r = paired_bootstrap(a, b, resamples=resamples, seed=i)
        if r.ci_low <= true_diff <= r.ci_high:
            covered += 1
    return covered / trials


def test_ci_coverage_is_near_nominal_ci_tier() -> None:
    # Moderate run for CI: coverage must land near 0.95 (loose band for speed).
    cov = _coverage(trials=1500, resamples=300)
    assert 0.90 <= cov <= 0.99, f"coverage {cov} off nominal 0.95"


@pytest.mark.local
def test_ci_coverage_full_20k() -> None:
    cov = _coverage(trials=20000, resamples=400)
    assert 0.94 <= cov <= 0.96, f"coverage {cov} not tight around 0.95"
