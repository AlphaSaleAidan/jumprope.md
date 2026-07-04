"""S4 — the jrope-bench front door: convert, stub-endpoint sweep, artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ropebench.convert import from_claude_code, write_bench_jsonl
from ropebench.models import OpenAICompatModel
from ropebench.regimes import default_regimes
from ropebench.report import report_card, report_json
from ropebench.runner import run_scenario
from ropebench.transcript import load

CC_FIXTURE = Path(__file__).parent / "fixtures" / "session.jsonl"


def test_convert_claude_code_to_bench_schema(tmp_path: Path) -> None:
    out = tmp_path / "bench.jsonl"
    n = write_bench_jsonl(from_claude_code(CC_FIXTURE), out)
    assert n > 0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    for row in rows:  # schema: role + content, nothing else required
        assert set(row) == {"role", "content"}
        assert row["role"] in ("user", "assistant")
        assert isinstance(row["content"], str) and row["content"]


def test_loader_accepts_bench_schema(tmp_path: Path) -> None:
    bench = tmp_path / "bench.jsonl"
    write_bench_jsonl(from_claude_code(CC_FIXTURE), bench)
    loaded = load(bench)
    assert loaded.stats.turns_kept > 0
    assert loaded.stats.probes >= 3


def test_stub_endpoint_sweep_produces_valid_artifacts(tmp_path: Path) -> None:
    """CI-tier e2e: run the front door against a stub OpenAI-compatible
    endpoint (no network) → schema-checked report_card.md + report.json."""
    loaded = load(CC_FIXTURE)

    def stub_chat(messages: list[dict[str, str]]) -> str:
        # Always answers with the last distinctive-looking token in context —
        # a deterministic stand-in for a model, no network.
        return "the value is 8092 per the context"

    model = OpenAICompatModel(
        base_url="http://stub/v1", model="stub-model",
        chat_fn=stub_chat, cache_dir=tmp_path / "cache",
    )
    metrics = run_scenario(loaded.scenario, default_regimes(only=["rope", "carry"]), model)

    card = report_card(metrics, "stub-model", seeds=[-1], n_turns=loaded.scenario.n_turns)
    assert "# RopeBench report card" in card
    assert "Paired comparison" in card

    blob = report_json(metrics, "stub-model", seeds=[-1], n_turns=loaded.scenario.n_turns)
    # report.json schema: the fields a third party posts to prove a reproduction.
    assert blob["model"] == "stub-model"
    assert set(blob["conditions"]) == {"full-history", "rope"}  # type: ignore[arg-type]
    for cond in blob["conditions"].values():  # type: ignore[attr-defined]
        assert {"accuracy", "total_tokens", "efficiency", "n_probes"} <= set(cond)
    assert "rope_vs_full-history" in blob["paired"]  # type: ignore[operator]
    json.dumps(blob)  # must be JSON-serializable


def test_cli_convert_and_run(tmp_path: Path) -> None:
    bench = tmp_path / "bench.jsonl"
    conv = subprocess.run(
        [sys.executable, "-m", "ropebench.cli", "convert", str(CC_FIXTURE), str(bench)],
        capture_output=True, text=True, check=False,
    )
    assert conv.returncode == 0 and bench.exists()

    run = subprocess.run(
        [sys.executable, "-m", "ropebench.cli", "run", "--transcript", str(bench),
         "--mode", "scripted", "--conditions", "rope,carry,summarize",
         "--out", str(tmp_path / "out")],
        capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    out = tmp_path / "out"
    assert (out / "report_card.md").exists()
    blob = json.loads((out / "report.json").read_text())
    assert set(blob["conditions"]) == {"full-history", "rope", "summary"}
