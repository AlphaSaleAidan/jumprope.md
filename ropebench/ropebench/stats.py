"""Paired statistics for condition comparisons — the S1 hardening core.

Conditions are scored on the SAME probes, so comparisons are paired: for each
probe we have a hit/miss under condition A and under condition B. The quantity
of interest is the paired accuracy difference (mean A-hit minus mean B-hit).
We attach a bootstrap 95% CI to it (resample probes with replacement) and read
a verdict from whether the CI clears zero.

Pure stdlib, deterministic under a seed — no numpy, no network.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

VERDICT_BETTER = "A-better"
VERDICT_WORSE = "A-worse"
VERDICT_PARITY = "parity"


@dataclass(frozen=True)
class PairedResult:
    n: int
    mean_a: float
    mean_b: float
    diff: float  # mean_a - mean_b
    ci_low: float
    ci_high: float
    wins: int  # probes where A hit and B missed
    losses: int  # probes where B hit and A missed
    ties: int
    verdict: str  # A-better / A-worse / parity (relative to A)

    def claim_phrase(self, a_name: str, b_name: str) -> str:
        """Prose that respects the CI — superiority only if it clears zero."""
        pa, pb = f"{self.mean_a:.0%}", f"{self.mean_b:.0%}"
        ci = f"95% CI [{self.ci_low:+.1%}, {self.ci_high:+.1%}], n={self.n}"
        if self.verdict == VERDICT_BETTER:
            return f"{a_name} beats {b_name} ({pa} vs {pb}; {ci})"
        if self.verdict == VERDICT_WORSE:
            return f"{a_name} trails {b_name} ({pa} vs {pb}; {ci})"
        return (
            f"{a_name} at parity with {b_name} ({pa} vs {pb}; {ci}) — "
            "the difference is not distinguishable from zero"
        )


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation percentile on a pre-sorted list (q in [0, 1])."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(sorted_vals):
        return sorted_vals[-1]
    return sorted_vals[lo] * (1 - frac) + sorted_vals[lo + 1] * frac


def paired_bootstrap(
    a_hits: list[int],
    b_hits: list[int],
    resamples: int = 10_000,
    seed: int = 0,
    alpha: float = 0.05,
) -> PairedResult:
    """Bootstrap CI on the paired accuracy difference mean(a) - mean(b).

    ``a_hits`` and ``b_hits`` are aligned per-probe 0/1 outcomes.
    """
    if len(a_hits) != len(b_hits):
        raise ValueError("paired inputs must have equal length")
    n = len(a_hits)
    if n == 0:
        raise ValueError("no probes to compare")
    if any(h not in (0, 1) for h in a_hits + b_hits):
        raise ValueError("hits must be 0 or 1")

    mean_a = sum(a_hits) / n
    mean_b = sum(b_hits) / n
    diff = mean_a - mean_b
    deltas = [a - b for a, b in zip(a_hits, b_hits, strict=True)]
    wins = sum(1 for d in deltas if d > 0)
    losses = sum(1 for d in deltas if d < 0)
    ties = n - wins - losses

    rng = random.Random(seed)
    boot: list[float] = []
    for _ in range(resamples):
        total = 0
        for _ in range(n):
            total += deltas[rng.randrange(n)]
        boot.append(total / n)
    boot.sort()
    ci_low = _percentile(boot, alpha / 2)
    ci_high = _percentile(boot, 1 - alpha / 2)

    if ci_low > 0:
        verdict = VERDICT_BETTER
    elif ci_high < 0:
        verdict = VERDICT_WORSE
    else:
        verdict = VERDICT_PARITY

    return PairedResult(
        n=n, mean_a=mean_a, mean_b=mean_b, diff=diff,
        ci_low=ci_low, ci_high=ci_high,
        wins=wins, losses=losses, ties=ties, verdict=verdict,
    )
