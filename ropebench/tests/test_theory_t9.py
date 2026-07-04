"""T9 — the rope+vault pattern on a REAL, large codebase (Python 3.12 stdlib).

Part A (the strong result): a big codebase is full of near-duplicate symbols —
hundreds of same-named functions. Semantic search cannot say WHICH `close` you
meant, so recall of a specific one tracks the k/(N+1) coin flip as duplicates
grow. An exact file::symbol handle (the rope's KEYS mechanism) fetches the right
one every time. This is T7 confirmed on genuine code, not synthetic fixtures.

Part B: no lost-in-the-middle for a distinctive marker even at ~80k tokens of
real code (12/12) — consistent with T5. Position is not the lever; disambiguation
among duplicates is, and exact addressing is what solves it.

The test pins the committed artifact so the finding can't silently rot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_ARTIFACT = Path(__file__).resolve().parents[1] / "results" / "t9-codescale" / "result.json"


def _load() -> dict:
    if not _ARTIFACT.exists():
        pytest.skip("T9 artifact absent (run research/exp_t9_codescale.py --live)")
    return json.loads(_ARTIFACT.read_text())


def test_codebase_does_not_fit_and_exact_beats_semantic() -> None:
    data = _load()
    # the sampled codebase is far larger than any context window.
    assert data["code_tokens"] > 500_000, data["code_tokens"]

    part_a = {int(k): v for k, v in data["part_a"].items()}
    # exact addressing is perfect at every duplicate count.
    for n, row in part_a.items():
        assert row["rope"] >= 0.99, (n, row)
    # with real near-duplicates present, semantic recall collapses far below
    # exact, and sits near the coin-flip line.
    for n in (8, 16):
        if n in part_a and part_a[n]["n_targets"] >= 10:
            assert part_a[n]["flat"] <= part_a[n]["chance"] + 0.15, part_a[n]
            assert part_a[n]["rope"] - part_a[n]["flat"] > 0.5, part_a[n]


def test_no_litm_for_distinctive_marker_at_80k() -> None:
    data = _load()
    if "part_b" not in data:
        pytest.skip("Part B (live) not present in artifact")
    rows = data["part_b"]["rows"]
    assert max(r["ctx_tokens"] for r in rows) > 60_000
    # a distinctive marker is recalled regardless of depth — position isn't the
    # failure mode (the duplicate-disambiguation of Part A is).
    recall = sum(r["hit"] for r in rows) / len(rows)
    assert recall >= 0.9, rows
