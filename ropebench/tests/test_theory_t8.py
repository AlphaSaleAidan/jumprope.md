"""T8 — noise robustness: the rope degrades gracefully under filler where the
lossy baselines collapse, and its relative advantage WIDENS with noise.

As a session gets chattier, truncate lets facts scroll out and summary compacts
them away; the rope distills and keeps a durable structured core. The rope's
margin over both grows with the filler ratio.
"""

from __future__ import annotations

from ropebench.runner import run_benchmark


def test_rope_more_noise_robust_and_gap_widens() -> None:
    low = run_benchmark(seeds=[1, 2], n_turns=80, chatty=0)
    high = run_benchmark(seeds=[1, 2], n_turns=80, chatty=16)

    # rope beats both lossy baselines at every noise level.
    for m in (low, high):
        assert m["rope"].accuracy() > m["truncate"].accuracy()
        assert m["rope"].accuracy() > m["summary"].accuracy()

    # the margin over the lossy baselines widens as filler grows.
    gap_low = low["rope"].accuracy() - low["truncate"].accuracy()
    gap_high = high["rope"].accuracy() - high["truncate"].accuracy()
    assert gap_high > gap_low, (gap_low, gap_high)
