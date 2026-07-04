"""T7 — distractor anti-fragility: exact addressing survives semantic interference.

Near-duplicate facts (same wording, different value token) are nearly
indistinguishable to a semantic retriever, so a flat vault's top-k recall of a
*specific* target collapses toward chance k/(N+1) as N distractors flood in. The
rope gives every archived fact a turn-stamped KEYS handle → an exact
content-addressed fetch that is immune to neighbourhood density.

This is the mechanism behind T3 (structure beats a flat blob) isolated to the
retrieval tier: what makes structure win is that it makes old facts *addressable*.
"""

from __future__ import annotations

import pytest

from research.exp_t7_distractors import aggregate


@pytest.mark.local
def test_flat_semantic_collapses_but_exact_holds() -> None:
    res = aggregate("symbolic-en", seeds=4, n_targets=20)
    # With no distractors both recover the target.
    assert res[0]["flat"] > 0.9
    assert res[0]["rope"] > 0.99
    # As near-duplicates flood in, semantic recall collapses...
    assert res[32]["flat"] < 0.25, res[32]
    # ...while exact content-addressing is untouched by neighbourhood density.
    for n in res:
        assert res[n]["rope"] > 0.99, (n, res[n])


@pytest.mark.local
def test_flat_recall_tracks_chance() -> None:
    """The collapse isn't a bug — semantic search on near-identical text is
    doing no better than random among the N+1 near-duplicates. Recall stays
    at or below the k/(N+1) chance line everywhere past the crossover."""
    res = aggregate("symbolic-en", seeds=4, n_targets=20)
    for n in (8, 16, 32, 64):
        assert res[n]["flat"] <= res[n]["chance"] + 0.10, (n, res[n])


@pytest.mark.local
def test_ai_native_does_not_rescue_semantic_and_exact_still_wins() -> None:
    """User hypothesis: does an AI-native rope strengthen the outcome? Denser
    coding cannot rescue the *semantic* path (near-duplicates stay near-
    identical after coding) — but exact addressing holds regardless, so the
    rope's advantage over a flat blob is preserved under ai-native too."""
    res = aggregate("ai-native", seeds=4, n_targets=20)
    assert res[32]["flat"] < 0.30, res[32]
    assert res[32]["rope"] > 0.99, res[32]
    # The rope-vs-flat gap under interference is large under ai-native as well.
    assert res[32]["rope"] - res[32]["flat"] > 0.6, res[32]
