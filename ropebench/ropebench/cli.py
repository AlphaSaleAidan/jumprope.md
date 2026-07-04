"""``ropebench`` / ``jrope-bench`` CLI — measure context strategies on your
own sessions and models in one command."""

from __future__ import annotations

import argparse
import json
import os
import shlex
from pathlib import Path

from .convert import from_claude_code, write_bench_jsonl
from .models import CommandModel, OpenAICompatModel, ScriptedModel
from .pricing import enforce_budget, estimate_cost
from .regimes import default_regimes
from .report import csv_rows, markdown, report_card, report_json
from .runner import RegimeMetrics, run_scenario
from .scenario import generate
from .transcript import load as load_transcript


def _build_model(
    mode: str, cmd: str, base_url: str, model_id: str, api_key: str
) -> ScriptedModel | OpenAICompatModel | CommandModel | None:
    if mode == "live-cmd":
        if not cmd:
            print("live-cmd mode needs --cmd")
            return None
        return CommandModel(argv=shlex.split(cmd))
    if mode == "live":
        if not base_url or not model_id:
            print("live mode needs --base-url and --model (or ROPEBENCH_* env vars)")
            return None
        return OpenAICompatModel(base_url=base_url, model=model_id,
                                 api_key=api_key, cache_dir="bench_cache")
    return ScriptedModel()


def _conditions(raw: str) -> list[str] | None:
    return [c.strip() for c in raw.split(",") if c.strip()] if raw else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jrope-bench",
        description="Benchmark LLM context-handoff strategies on your own sessions",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a sweep (synthetic or --transcript)")
    run.add_argument("--transcript", default=None,
                     help="replay a real session (.jsonl, bench or Claude Code schema)")
    run.add_argument("--mode", choices=["scripted", "live", "live-cmd"], default="scripted")
    run.add_argument("--runs", "--seeds", type=int, default=3, dest="runs",
                     help="number of seeds (synthetic mode)")
    run.add_argument("--turns", type=int, default=80)
    run.add_argument("--max-turns", type=int, default=120, help="transcript cap")
    run.add_argument("--chatty", type=int, default=0)
    run.add_argument("--conditions", default="",
                     help="comma list: rope,carry,truncate,summarize,unbound,streaming")
    run.add_argument("--out", default=None, help="artifact directory")
    run.add_argument("--cmd", default="")
    run.add_argument("--base-url", default=os.environ.get("ROPEBENCH_BASE_URL", ""))
    run.add_argument("--model", default=os.environ.get("ROPEBENCH_MODEL", "scripted"))
    run.add_argument("--api-key", default=os.environ.get("ROPEBENCH_API_KEY", ""))
    run.add_argument("--redact", action="store_true")

    conv = sub.add_parser("convert", help="Claude Code .jsonl → bench schema .jsonl")
    conv.add_argument("source")
    conv.add_argument("out")
    return parser


def _write_artifacts(
    out_dir: str, metrics: dict[str, RegimeMetrics], model: str,
    seeds: list[int], n_turns: int,
) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(markdown(metrics) + "\n", encoding="utf-8")
    (out / "report_card.md").write_text(
        report_card(metrics, model, seeds, n_turns), encoding="utf-8"
    )
    (out / "report.json").write_text(
        json.dumps(report_json(metrics, model, seeds, n_turns), indent=2),
        encoding="utf-8",
    )
    (out / "results.csv").write_text(csv_rows(metrics), encoding="utf-8")
    print(f"\nwrote {out}/ (report_card.md, report.json, report.md, results.csv)")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "convert":
        n = write_bench_jsonl(from_claude_code(args.source), args.out)
        print(f"converted {n} messages → {args.out}")
        return 0

    model = _build_model(args.mode, args.cmd, args.base_url, args.model, args.api_key)
    if model is None:
        return 2
    only = _conditions(args.conditions)

    # S0: paid (--mode live) sweeps must pass a budget preflight. A free
    # scripted dry-run of the same shape gives exact payload token counts.
    if args.mode == "live" and not args.transcript:
        from .pricing import BudgetExceeded
        dry = run_scenario(
            generate(1, n_turns=args.turns, chatty=args.chatty),
            default_regimes(only=only), ScriptedModel(),
        )
        input_tok = sum(m.probe_tokens for m in dry.values()) * args.runs
        calls = sum(len(m.probe_results) for m in dry.values()) * args.runs
        try:
            enforce_budget(estimate_cost(args.model, input_tok, calls))
        except BudgetExceeded as exc:
            print(f"aborted: {exc}")
            return 3
    model_label = args.model if args.mode != "scripted" else "scripted"

    if args.transcript:
        loaded = load_transcript(
            args.transcript, max_turns=args.max_turns, redact=args.redact
        )
        s = loaded.stats
        print(
            f"transcript: {s.turns_kept} turns kept of {s.total_messages} messages, "
            f"{s.probes} probes from {s.unique_values} distinct values"
            + ("  [REDACTED]" if s.redacted else "")
        )
        if s.probes == 0:
            print("no probes could be mined from this transcript")
            return 1
        metrics = run_scenario(loaded.scenario, default_regimes(only=only), model)
        n_turns, seeds = loaded.scenario.n_turns, [-1]
    else:
        seeds = list(range(1, args.runs + 1))
        runs = [
            run_scenario(
                generate(seed, n_turns=args.turns, chatty=args.chatty),
                default_regimes(only=only), model,
            )
            for seed in seeds
        ]
        from .runner import merge
        metrics = merge(runs)
        n_turns = args.turns

    print(markdown(metrics))
    if args.out:
        _write_artifacts(args.out, metrics, model_label, seeds, n_turns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
