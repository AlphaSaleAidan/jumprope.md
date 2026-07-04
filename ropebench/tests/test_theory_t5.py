"""T5 — does position in the context change recall? Measured null.

The scripted reader is position-invariant by construction, so T5 needs a live
model. A bounded free sweep (local `claude -p --model haiku`, no Meridian) placed
one needle at depth 5% / 50% / 95% across contexts of 547 → 21,417 tokens.

Result: 72/72 recalled — NO lost-in-the-middle for a single needle up to 21k
tokens. This is recorded as an honest null: position is not where the rope wins.
The rope's edge is cost (T1/T4) and noise-robustness (T8), not dodging a
positional weakness that, at rope-relevant scales and with a modern model, does
not bite. The test pins the artifact so the null can't silently rot into a
false "confirmed".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_ARTIFACT = Path(__file__).resolve().parents[1] / "results" / "t5-ordering" / "result.json"


def _load() -> dict:
    if not _ARTIFACT.exists():
        pytest.skip("T5 artifact not present (run research/exp_t5_ordering.py)")
    return json.loads(_ARTIFACT.read_text())


def _recall_by_depth(rows: list[dict], size: str) -> dict[float, float]:
    out: dict[float, float] = {}
    depths = sorted({r["depth"] for r in rows})
    for d in depths:
        sel = [r for r in rows if r["size"] == size and r["depth"] == d]
        out[d] = sum(r["hit"] for r in sel) / len(sel) if sel else 0.0
    return out


def test_no_lost_in_the_middle_up_to_21k() -> None:
    data = _load()
    rows = data["rows"]
    sizes = {r["size"] for r in rows}
    assert {"small", "large", "xlarge"} <= sizes
    # the sweep actually exercised a large context (else the null is vacuous).
    assert max(r["ctx_tokens"] for r in rows) > 15_000
    for size in sizes:
        by_depth = _recall_by_depth(rows, size)
        edges = [by_depth[min(by_depth)], by_depth[max(by_depth)]]
        middle = by_depth[sorted(by_depth)[len(by_depth) // 2]]
        # position-flat: the middle is not a recall valley (no LITM dip).
        assert middle >= min(edges) - 1e-9, (size, by_depth)
        # and recall stays high everywhere at these scales.
        assert min(by_depth.values()) >= 0.75, (size, by_depth)
