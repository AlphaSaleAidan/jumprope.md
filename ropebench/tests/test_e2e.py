"""End-to-end scripted sweep: the regime-ordering claims RopeBench exists
to test, asserted deterministically (information availability)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ropebench.report import csv_rows, markdown
from ropebench.runner import run_benchmark

SEEDS = [1, 2]
TURNS = 80


def sweep() -> dict[str, object]:
    return run_benchmark(seeds=SEEDS, n_turns=TURNS)  # type: ignore[return-value]


def test_regime_ordering_claims() -> None:
    metrics = run_benchmark(seeds=SEEDS, n_turns=TURNS)
    full, truncate = metrics["full-history"], metrics["truncate"]
    summary, rope = metrics["summary"], metrics["rope"]
    unbound = metrics["rope-unbound"]

    print("\n" + markdown(metrics))

    # The oracle is the ceiling and must be perfect for a literal reader.
    assert full.accuracy() == 1.0

    # Long-distance retention is where the strategy earns its keep:
    # rope must beat both lossy baselines decisively.
    assert rope.accuracy(bucket="long") > truncate.accuracy(bucket="long")
    assert rope.accuracy(bucket="long") > summary.accuracy(bucket="long")

    # Cost: rope must run at well under the oracle's spend.
    assert rope.total_tokens < 0.6 * full.total_tokens

    # Pareto: best accuracy-per-token of all four regimes.
    for other in (full, truncate, summary):
        assert rope.efficiency > other.efficiency, other.name

    # The retrieval tool must be load-bearing for rope, not decorative.
    assert rope.retrieval_rate > 0.15

    # Sanity floors — a regression in jumping-rope shows up here.
    assert rope.accuracy() >= 0.75
    assert rope.accuracy(kind="status") == 1.0  # glyphs survive compaction

    # UNBOUND mode: perfect verbatim recall — matches the oracle on every
    # cell, with zero retrieval (nothing ever leaves the rope).
    assert unbound.accuracy() == 1.0
    assert unbound.accuracy(bucket="long") == 1.0
    assert unbound.retrieval_rate == 0.0
    # Honest cost note, asserted so nobody quietly forgets it: on a
    # PRE-DISTILLED event stream the unbound rope costs MORE than the raw
    # oracle (per-record structure + legend). Its cost win is against real
    # chat transcripts (17-18% payload, measured in the adapter tests),
    # which this event-driven scenario does not model. See ROADMAP B4/B5.
    assert unbound.total_tokens > full.total_tokens
    assert unbound.total_tokens > rope.total_tokens


def test_summary_regime_fails_exactly_where_predicted() -> None:
    """The A12-adjacent claim: summarization loses trailing detail, so its
    long-distance fact recall collapses below every other regime."""
    metrics = run_benchmark(seeds=SEEDS, n_turns=TURNS)
    summary_long = metrics["summary"].accuracy(bucket="long")
    for name in ("full-history", "truncate", "rope"):
        assert summary_long <= metrics[name].accuracy(bucket="long")


def test_report_artifacts() -> None:
    metrics = run_benchmark(seeds=[1], n_turns=40)
    table = markdown(metrics)
    assert table.count("\n") >= 5
    assert "| rope |" in table
    rows = csv_rows(metrics)
    assert rows.splitlines()[0].startswith("regime,probe_tag")
    assert len(rows.splitlines()) == 1 + 5 * 30  # header + 5 regimes × 30 probes


def test_cli_scripted_run(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ropebench.cli", "run", "--mode", "scripted",
         "--seeds", "1", "--turns", "40", "--out", str(tmp_path / "results")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "| Regime |" in result.stdout
    assert (tmp_path / "results" / "report.md").exists()
    assert (tmp_path / "results" / "results.csv").exists()


def test_cli_live_requires_endpoint() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ropebench.cli", "run", "--mode", "live"],
        capture_output=True, text=True, check=False,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2
    assert "live mode needs" in result.stdout


def test_deterministic_across_runs() -> None:
    a = run_benchmark(seeds=[3], n_turns=40)
    b = run_benchmark(seeds=[3], n_turns=40)
    assert json.dumps(markdown(a)) == json.dumps(markdown(b))


def test_chatty_scenario_rope_efficiency_wins() -> None:
    """B5: with facts wrapped in conversational filler (real-transcript
    shape), bound rope keeps the best accuracy-per-token — full history
    pays for all the padding, the rope distills it."""
    metrics = run_benchmark(seeds=SEEDS, n_turns=TURNS, chatty=4)
    full = metrics["full-history"]
    rope = metrics["rope"]
    print("\n[chatty] " + markdown(metrics).splitlines()[-2])
    # Padding inflates the oracle's bill; the rope's efficiency lead widens.
    assert rope.efficiency > full.efficiency
    assert rope.total_tokens < full.total_tokens
    # Rope still recovers a solid majority of facts under the noise.
    assert rope.accuracy() >= 0.65
    # And the lossy baselines degrade hard on the padded stream.
    assert metrics["summary"].accuracy(bucket="long") < 0.3


def test_chatty_is_deterministic_and_preserves_values() -> None:
    from ropebench.scenario import generate

    a = generate(7, n_turns=60, chatty=4)
    b = generate(7, n_turns=60, chatty=4)
    assert a.turns == b.turns and a.probes == b.probes
    # chatty=0 must equal the default (no regression)
    assert generate(5).turns == generate(5, chatty=0).turns
    # the answer value survives the padding
    s = generate(3, n_turns=60, chatty=6)
    for probe in s.probes:
        if probe.kind in ("fact", "decision"):
            assert any(
                probe.expected_any[0] in e.text
                for turn in s.turns for e in turn
            ), probe.tag
