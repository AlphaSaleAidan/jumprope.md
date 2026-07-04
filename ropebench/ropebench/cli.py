"""``ropebench`` CLI: run the sweep, print the table, write artifacts."""

from __future__ import annotations

import argparse
import os
import shlex
from pathlib import Path

from .models import CommandModel, OpenAICompatModel, ScriptedModel
from .regimes import default_regimes
from .report import csv_rows, markdown
from .runner import run_benchmark, run_scenario
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
        return OpenAICompatModel(base_url=base_url, model=model_id, api_key=api_key)
    return ScriptedModel()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ropebench",
        description="Effectiveness benchmark for LLM context-handoff strategies",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the 4-regime sweep")
    run.add_argument("--mode", choices=["scripted", "live", "live-cmd"], default="scripted")
    run.add_argument("--seeds", type=int, default=3, help="number of seeds")
    run.add_argument("--turns", type=int, default=80)
    run.add_argument("--chatty", type=int, default=0,
                     help="wrap each fact in N sentences of filler "
                     "(models a real chatty transcript)")
    run.add_argument("--out", default=None, help="directory for report.md + results.csv")
    run.add_argument("--base-url", default=os.environ.get("ROPEBENCH_BASE_URL", ""))
    run.add_argument("--model", default=os.environ.get("ROPEBENCH_MODEL", ""))
    run.add_argument("--api-key", default=os.environ.get("ROPEBENCH_API_KEY", ""))
    run.add_argument(
        "--cmd", default="",
        help="live-cmd mode: shell command reading the prompt on stdin, "
        'replying on stdout (e.g. "claude -p --model haiku")',
    )

    replay = sub.add_parser(
        "replay", help="replay a real Claude Code .jsonl session through the regimes"
    )
    replay.add_argument("transcript", help="path to a Claude Code session .jsonl")
    replay.add_argument("--mode", choices=["scripted", "live", "live-cmd"],
                        default="scripted")
    replay.add_argument("--max-turns", type=int, default=120)
    replay.add_argument("--out", default=None)
    replay.add_argument("--cmd", default="")
    replay.add_argument("--base-url", default=os.environ.get("ROPEBENCH_BASE_URL", ""))
    replay.add_argument("--model", default=os.environ.get("ROPEBENCH_MODEL", ""))
    replay.add_argument("--api-key", default=os.environ.get("ROPEBENCH_API_KEY", ""))
    replay.add_argument(
        "--redact", action="store_true",
        help="keep raw session text out of artifacts (tags + hit/miss only)",
    )
    return parser


def _write_artifacts(out_dir: str, table: str, metrics: object) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(table + "\n", encoding="utf-8")
    (out / "results.csv").write_text(csv_rows(metrics), encoding="utf-8")  # type: ignore[arg-type]
    print(f"\nwrote {out}/report.md and {out}/results.csv")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    model = _build_model(
        args.mode, args.cmd, args.base_url, args.model, args.api_key
    )
    if model is None:
        return 2

    if args.command == "replay":
        loaded = load_transcript(
            args.transcript, max_turns=args.max_turns, redact=args.redact
        )
        s = loaded.stats
        print(
            f"transcript: {s.turns_kept} turns kept of {s.total_messages} messages, "
            f"{s.probes} probes mined from {s.unique_values} distinct values"
            + ("  [REDACTED]" if s.redacted else "")
        )
        if s.probes == 0:
            print("no probes could be mined from this transcript")
            return 1
        metrics = run_scenario(loaded.scenario, default_regimes(), model)
        table = markdown(metrics)
        print(table)
        if args.out:
            _write_artifacts(args.out, table, metrics)
        return 0

    metrics = run_benchmark(
        seeds=list(range(1, args.seeds + 1)), n_turns=args.turns, model=model,
        chatty=getattr(args, "chatty", 0),
    )
    table = markdown(metrics)
    print(table)
    if args.out:
        _write_artifacts(args.out, table, metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
