"""S3 / B6 — streaming eviction modeled in-bench with the REAL policy.

Closes the gap the retrospective flagged: unbound mode's economics used to
rest on adapter tests. Here the actual ``apply_streaming_policy`` drives the
cost accounting, turn by turn, so the numbers are the bench's own.
"""

from __future__ import annotations

from pathlib import Path

from ropebench.regimes import FullHistoryRegime, StreamingRopeRegime
from ropebench.scenario import generate


def _replay(regime: object, chatty: int, tmp: Path) -> int:
    s = generate(1, n_turns=60, chatty=chatty)
    for t in range(1, 61):
        regime.observe(t, s.turns[t - 1])  # type: ignore[attr-defined]
        regime.end_turn()  # type: ignore[attr-defined]
    return regime.total_tokens  # type: ignore[attr-defined]


def test_streaming_cost_is_flat_while_full_history_explodes(tmp_path: Path) -> None:
    """The core B6 claim: streaming evicts the chatty transcript, so its
    cumulative cost is ~invariant to verbosity while full-history scales."""
    stream = {c: _replay(StreamingRopeRegime(data_dir=tmp_path / f"s{c}"), c, tmp_path)
              for c in (0, 16)}
    full = {c: _replay(FullHistoryRegime(), c, tmp_path) for c in (0, 16)}

    # full-history grows a lot with filler (4× padding → several× tokens).
    assert full[16] > 5 * full[0]
    # streaming stays nearly flat — it evicts the padding (within ~25%).
    assert stream[16] < 1.25 * stream[0]


def test_streaming_beats_full_history_on_chatty_transcripts(tmp_path: Path) -> None:
    """On a realistically chatty transcript streaming is far cheaper; on a
    filler-free stream it is not (nothing to evict) — reported honestly."""
    stream16 = _replay(StreamingRopeRegime(data_dir=tmp_path / "s16"), 16, tmp_path)
    full16 = _replay(FullHistoryRegime(), 16, tmp_path)
    assert stream16 < 0.5 * full16, "heavy filler → streaming well under half the cost"

    stream0 = _replay(StreamingRopeRegime(data_dir=tmp_path / "s0"), 0, tmp_path)
    full0 = _replay(FullHistoryRegime(), 0, tmp_path)
    assert stream0 > full0, "no filler → streaming loses; honest floor, not hidden"


def test_streaming_uses_the_real_policy_not_a_reimplementation() -> None:
    """Guard against drift: the regime must call the shipped policy."""
    import inspect

    src = inspect.getsource(StreamingRopeRegime.observe)
    assert "apply_streaming_policy" in src
