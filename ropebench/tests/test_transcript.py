"""Phase 5 — transcript replay: loader, cloze probes, redaction, e2e."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ropebench.regimes import default_regimes
from ropebench.runner import run_scenario
from ropebench.transcript import load

FIXTURE = Path(__file__).parent / "fixtures" / "session.jsonl"


def test_loads_and_mines_probes() -> None:
    loaded = load(FIXTURE)
    assert loaded.stats.turns_kept > 50
    assert loaded.stats.probes >= 3, "should mine several recurring-value probes"
    # every probe's answer is a real distinctive token, asked after it appeared
    for probe in loaded.scenario.probes:
        assert probe.expected_any[0]
        assert probe.turn > probe.ref_turn


def test_ground_truth_is_actually_in_the_transcript() -> None:
    loaded = load(FIXTURE)
    body = "\n".join(e.text for turn in loaded.scenario.turns for e in turn)
    for probe in loaded.scenario.probes:
        assert probe.expected_any[0] in body, probe.tag


def test_redaction_keeps_raw_text_out_of_questions() -> None:
    loaded = load(FIXTURE, redact=True)
    assert loaded.stats.redacted
    for probe in loaded.scenario.probes:
        # the fact clause is replaced by a placeholder; only the value remains
        assert "[fact #" in probe.question


def test_scripted_replay_scores_all_regimes() -> None:
    loaded = load(FIXTURE)
    metrics = run_scenario(loaded.scenario, default_regimes(), __import__(
        "ropebench.models", fromlist=["ScriptedModel"]).ScriptedModel())
    assert set(metrics) == {
        "full-history", "truncate", "summary", "rope", "rope-unbound"
    }
    # the oracle must recover its own verbatim facts
    assert metrics["full-history"].accuracy() >= 0.8
    # unbound rope keeps everything too
    assert metrics["rope-unbound"].accuracy() >= 0.8


def test_malformed_lines_are_skipped() -> None:
    bad = Path(FIXTURE).with_suffix(".bad.jsonl")
    bad.write_text(
        "not json\n"
        + json.dumps({"type": "user", "message": {"role": "user",
          "content": "port 9091 is the metrics endpoint we keep referencing"}})
        + "\n{ broken\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant",
          "content": "confirmed, port 9091 stays the metrics endpoint for now"}})
        + "\n"
    )
    loaded = load(bad)
    assert loaded.stats.turns_kept == 2  # two valid messages, junk skipped
    bad.unlink()


def test_cli_replay(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ropebench.cli", "run", "--transcript", str(FIXTURE),
         "--mode", "scripted", "--out", str(tmp_path / "out")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "transcript:" in result.stdout
    assert "| rope |" in result.stdout
    assert (tmp_path / "out" / "report.md").exists()


def test_empty_and_valueless_transcripts_dont_crash(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert load(empty).stats.probes == 0

    valueless = tmp_path / "valueless.jsonl"
    valueless.write_text("\n".join(
        json.dumps({"type": "user", "message": {"role": "user",
                    "content": "please keep tidying the helper code and move along"}})
        for _ in range(30)
    ))
    loaded = load(valueless)
    assert loaded.stats.turns_kept == 30
    assert loaded.stats.probes == 0  # nothing distinctive to ask about
