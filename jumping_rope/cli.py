"""``jrope`` CLI: init, log, status, jump, query, export."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .session import JumpConfig, JumpingRopeSession

DEFAULT_DATA_DIR = ".jrope"


def _add_data_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        help=f"session data directory (default: {DEFAULT_DATA_DIR})",
    )


def _open_session(args: argparse.Namespace) -> JumpingRopeSession:
    data_dir = Path(args.data_dir)
    if not (data_dir / "session.json").exists():
        print(f"error: no session at {data_dir}; run `jrope init` first", file=sys.stderr)
        raise SystemExit(2)
    return JumpingRopeSession(data_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jrope",
        description="Jumping Rope: two-tier context handoff for LLM sessions",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="initialize a session")
    _add_data_dir(p_init)
    p_init.add_argument("--session-id", default=None)
    p_init.add_argument(
        "--mode", default="bound", choices=["bound", "unbound"],
        help="bound: hard rope budget + jumps; unbound: rope grows freely, "
        "transcript evicted continuously",
    )
    p_init.add_argument("--rope-budget-tokens", type=int, default=2_000)
    p_init.add_argument("--jump-threshold-tokens", type=int, default=12_000)
    p_init.add_argument("--jump-every-n-turns", type=int, default=8)
    p_init.add_argument(
        "--profile", default="symbolic-en", choices=["symbolic-en", "cjk-dense"]
    )

    p_log = sub.add_parser("log", help="record a meaningful change")
    _add_data_dir(p_log)
    p_log.add_argument("section", choices=["state", "goal", "decision", "delta", "open"])
    p_log.add_argument("content")
    p_log.add_argument("--key", default=None, help="STATE key")
    p_log.add_argument("--path", default=None, help="DELTA path")
    p_log.add_argument("--change-class", default="mod", help="DELTA change class")
    p_log.add_argument("--priority", type=int, default=2, choices=[0, 1, 2, 3])
    p_log.add_argument(
        "--status", default="pending", choices=["pending", "active", "done", "failed"]
    )
    p_log.add_argument("--reason", default="", help="DECISIONS reason")
    p_log.add_argument("--raw", action="store_true", help="skip notation densify")

    p_status = sub.add_parser("status", help="show session status as JSON")
    _add_data_dir(p_status)

    p_jump = sub.add_parser("jump", help="perform a jump; prints the rope")
    _add_data_dir(p_jump)

    p_retire = sub.add_parser(
        "retire",
        help="compact an unbound session down to a bound rope (prints it)",
    )
    _add_data_dir(p_retire)
    p_retire.add_argument("--budget", type=int, default=2_000)

    p_query = sub.add_parser("query", help="retrieve demoted content")
    _add_data_dir(p_query)
    p_query.add_argument("text")
    p_query.add_argument("-k", type=int, default=5)

    p_export = sub.add_parser("export", help="export rope + store to JSON")
    _add_data_dir(p_export)
    p_export.add_argument("--out", default="-", help="output file (default stdout)")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "init":
        config = JumpConfig(
            rope_budget_tokens=0 if args.mode == "unbound" else args.rope_budget_tokens,
            jump_threshold_tokens=args.jump_threshold_tokens,
            jump_every_n_turns=args.jump_every_n_turns,
            notation_profile=args.profile,
        )
        session = JumpingRopeSession(
            Path(args.data_dir), session_id=args.session_id, config=config
        )
        print(f"initialized session {session.meta.session_id} in {args.data_dir}")
        session.close()
        return 0

    session = _open_session(args)
    try:
        if args.command == "log":
            session.record_event(
                args.section,
                args.content,
                priority=args.priority,
                status=args.status,
                path=args.path,
                change_class=args.change_class,
                key=args.key,
                reason=args.reason,
                densify=not args.raw,
            )
            print(f"logged {args.section} event ({session.status()['rope_tokens']} rope tokens)")
        elif args.command == "status":
            print(json.dumps(session.status(), indent=2))
        elif args.command == "jump":
            print(session.jump(), end="")
        elif args.command == "retire":
            print(session.retire(budget_tokens=args.budget), end="")
        elif args.command == "query":
            result = session.retrieve(args.text, k=args.k)
            print(result if result else "NO-HIT")
        elif args.command == "export":
            payload = json.dumps(
                {
                    "rope": session.rope.render(),
                    "status": session.status(),
                    "records": [
                        dataclasses.asdict(r)
                        for r in session.store.dump(session.meta.session_id)
                    ],
                },
                indent=2,
            )
            if args.out == "-":
                print(payload)
            else:
                Path(args.out).write_text(payload, encoding="utf-8")
                print(f"exported to {args.out}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
