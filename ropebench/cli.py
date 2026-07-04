"""``ropebench`` CLI: run the sweep, print the table, write artifacts."""

from __future__ import annotations

import argparse
import os
import shlex
from pathlib import Path

from .models import CommandModel, OpenAICompatModel, ScriptedModel
from .report import csv_rows, markdown
from .runner import run_benchmark


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
    run.add_argument("--out", default=None, help="directory for report.md + results.csv")
    run.add_argument("--base-url", default=os.environ.get("ROPEBENCH_BASE_URL", ""))
    run.add_argument("--model", default=os.environ.get("ROPEBENCH_MODEL", ""))
    run.add_argument("--api-key", default=os.environ.get("ROPEBENCH_API_KEY", ""))
    run.add_argument(
        "--cmd", default="",
        help="live-cmd mode: shell command reading the prompt on stdin, "
        'replying on stdout (e.g. "claude -p --model haiku")',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    model: ScriptedModel | OpenAICompatModel | CommandModel
    if args.mode == "live-cmd":
        if not args.cmd:
            print("live-cmd mode needs --cmd")
            return 2
        model = CommandModel(argv=shlex.split(args.cmd))
    elif args.mode == "live":
        if not args.base_url or not args.model:
            print("live mode needs --base-url and --model (or ROPEBENCH_* env vars)")
            return 2
        model = OpenAICompatModel(
            base_url=args.base_url, model=args.model, api_key=args.api_key
        )
    else:
        model = ScriptedModel()

    metrics = run_benchmark(
        seeds=list(range(1, args.seeds + 1)), n_turns=args.turns, model=model
    )
    table = markdown(metrics)
    print(table)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.md").write_text(table + "\n", encoding="utf-8")
        (out / "results.csv").write_text(csv_rows(metrics), encoding="utf-8")
        print(f"\nwrote {out}/report.md and {out}/results.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
