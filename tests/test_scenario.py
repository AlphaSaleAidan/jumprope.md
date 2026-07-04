"""Scenario generator: determinism, ground truth, probe stratification."""

from __future__ import annotations

from ropebench.scenario import LONG, MEDIUM, SHORT, generate


def test_same_seed_identical_scenario() -> None:
    a, b = generate(7), generate(7)
    assert a.turns == b.turns
    assert a.probes == b.probes


def test_different_seeds_differ() -> None:
    assert generate(1).probes != generate(2).probes


def test_probe_counts_and_stratification() -> None:
    scenario = generate(3)
    assert len(scenario.probes) == 16 + 8 + 6  # facts + decisions + goals
    buckets = {b: sum(p.bucket == b for p in scenario.probes)
               for b in (SHORT, MEDIUM, LONG)}
    assert all(count >= 5 for count in buckets.values()), buckets


def test_probes_never_precede_their_ground_truth() -> None:
    scenario = generate(11)
    for probe in scenario.probes:
        assert probe.turn >= probe.ref_turn
        assert probe.turn <= scenario.n_turns


def test_ground_truth_is_in_the_event_stream() -> None:
    scenario = generate(5)
    all_text = "\n".join(e.text for turn in scenario.turns for e in turn)
    for probe in scenario.probes:
        if probe.kind in ("fact", "decision"):
            assert any(exp in all_text for exp in probe.expected_any), probe.tag


def test_every_turn_has_filler_churn() -> None:
    scenario = generate(9)
    for turn_events in scenario.turns:
        assert any(e.kind == "filler" for e in turn_events)
