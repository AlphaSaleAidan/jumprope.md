#!/usr/bin/env python3
"""rope_ops.py — maintain ROPE.md for the jumping-rope Claude skill.

Full mode (jumping-rope package installed): thin wrapper around
JumpingRopeSession; state lives in .jrope/ and ROPE.md is mirrored to the
repo root. Degraded mode (no install, or JROPE_FORCE_DEGRADED=1): maintains a
spec-conformant ROPE.md at the repo root with a char-based token estimate and
demotes overflow to .rope_overflow.md instead of TurboVec.

Usage:
    rope_ops.py init   [--root DIR] [--budget N]
    rope_ops.py log    <state|goal|decision|delta|open> <content>
                       [--key K] [--path P] [--priority 0-3] [--reason R]
                       [--change-class C] [--status S] [--root DIR]
    rope_ops.py status [--root DIR]
    rope_ops.py jump   [--root DIR]
    rope_ops.py query  <text> [--root DIR]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path

ROPE_NAME = "ROPE.md"
OVERFLOW_NAME = ".rope_overflow.md"
DATA_DIR = ".jrope"
DEFAULT_BUDGET = 2000
SECTIONS = ("LEGEND", "STATE", "GOALS", "DECISIONS", "DELTA", "OPEN", "KEYS")

_LEGEND = (
    "glyphs: ✓=done ▶=active ✗=failed ◌=pending "
    "→=yields/then ∵=because +=and w/=with w/o=without |=field-sep\n"
    "records: D{n}|date|decision|reason · K{n}|topic|key · P0..P3=priority"
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _full_mode_available() -> bool:
    if os.environ.get("JROPE_FORCE_DEGRADED") == "1":
        return False
    try:
        import jumping_rope  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------- full mode


def _full(args: argparse.Namespace) -> int:
    from jumping_rope import JumpConfig, JumpingRopeSession

    root = Path(args.root)
    data_dir = root / DATA_DIR
    budget = getattr(args, "budget", DEFAULT_BUDGET)
    session = JumpingRopeSession(
        data_dir, config=JumpConfig(rope_budget_tokens=budget)
    )
    try:
        if args.command == "init":
            print(f"initialized session {session.meta.session_id} (full mode)")
        elif args.command == "log":
            session.record_event(
                args.section,
                args.content,
                key=args.key,
                path=args.path,
                priority=args.priority,
                status=args.status,
                change_class=args.change_class,
                reason=args.reason,
            )
            print(f"logged {args.section} (full mode)")
        elif args.command == "status":
            for k, v in session.status().items():
                print(f"{k}: {v}")
        elif args.command == "jump":
            sys.stdout.write(session.jump())
        elif args.command == "retire":
            sys.stdout.write(session.retire(budget_tokens=args.budget))
        elif args.command == "query":
            result = session.retrieve(args.text)
            print(result if result else "NO-HIT")
        shutil.copyfile(data_dir / ROPE_NAME, root / ROPE_NAME)
    finally:
        session.close()
    return 0


# ------------------------------------------------------------- degraded mode


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _read_sections(rope_path: Path) -> tuple[str, dict[str, list[str]]]:
    header = ""
    sections: dict[str, list[str]] = {s: [] for s in SECTIONS}
    current: str | None = None
    for line in rope_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ROPE"):
            header = line
        elif line.startswith("## "):
            current = line[3:].strip()
        elif current is not None and line.strip():
            sections.setdefault(current, []).append(line)
    return header, sections


def _write_sections(rope_path: Path, header: str, sections: dict[str, list[str]]) -> None:
    lines = [header]
    for name in SECTIONS:
        lines.append(f"## {name}")
        lines.extend(sections.get(name, []))
    rope_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _next_num(lines: list[str], prefix: str) -> int:
    best = 0
    for line in lines:
        m = re.match(rf"^(?:\S+ )?{prefix}(\d+)\|", line)
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


def _degraded_enforce(
    root: Path, header: str, sections: dict[str, list[str]], budget: int
) -> None:
    overflow = root / OVERFLOW_NAME

    def total() -> int:
        body = "\n".join([header] + [ln for s in SECTIONS for ln in sections[s]])
        return _est_tokens(body)

    while total() > budget:
        victim: str | None = None
        for section in ("DECISIONS", "DELTA"):
            if sections[section]:
                victim = sections[section].pop(0)
                break
        if victim is None:
            for priority in ("P3", "P2"):
                for i, line in enumerate(sections["OPEN"]):
                    if f"|{priority}|" in line:
                        victim = sections["OPEN"].pop(i)
                        break
                if victim is not None:
                    break
        if victim is None:
            break  # only never-demoted sections remain
        seq = sum(1 for _ in overflow.read_text(encoding="utf-8").splitlines()) + 1 \
            if overflow.exists() else 1
        key = f"ovf-{seq}"
        with overflow.open("a", encoding="utf-8") as fh:
            fh.write(f"{key}|{victim}\n")
        topic = " ".join(victim.split()[:6]).replace("|", "/")
        knum = _next_num(sections["KEYS"], "K")
        sections["KEYS"].append(f"K{knum}|{topic}|{key}")


def _degraded(args: argparse.Namespace) -> int:
    root = Path(args.root)
    rope_path = root / ROPE_NAME
    budget = getattr(args, "budget", DEFAULT_BUDGET)

    if args.command == "init" or not rope_path.exists():
        sid = "skill-" + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:8]
        header = f"# ROPE v1 | sess:{sid} | j:0 | t:{_now()}"
        sections = {s: [] for s in SECTIONS}
        sections["LEGEND"] = _LEGEND.splitlines()
        _write_sections(rope_path, header, sections)
        if args.command == "init":
            print(f"initialized {rope_path} (degraded mode: no TurboVec)")
            return 0

    header, sections = _read_sections(rope_path)

    if args.command == "log":
        text = args.content.replace("\n", "; ").replace("|", "/")
        if args.section == "state":
            key = (args.key or "note").replace(":", "=")
            sections["STATE"] = [
                ln for ln in sections["STATE"] if not ln.startswith(key + ":")
            ]
            sections["STATE"].append(f"{key}:{text}")
        elif args.section == "goal":
            glyphs = {"pending": "◌", "active": "▶", "done": "✓", "failed": "✗"}
            num = _next_num(sections["GOALS"], "G")
            sections["GOALS"].append(f"{glyphs.get(args.status, '◌')} G{num}|{text}")
        elif args.section == "decision":
            num = _next_num(sections["DECISIONS"], "D")
            reason = (args.reason or "").replace("|", "/")
            sections["DECISIONS"].append(f"D{num}|{_now().split('T')[0]}|{text}|{reason}")
        elif args.section == "delta":
            path = (args.path or "unknown").replace("|", "/")
            sections["DELTA"] = [
                ln for ln in sections["DELTA"] if not ln.startswith(path + "|")
            ]
            sections["DELTA"].append(f"{path}|{args.change_class}|{text}")
        elif args.section == "open":
            num = _next_num(sections["OPEN"], "O")
            sections["OPEN"].append(f"O{num}|P{args.priority}|{text}")
        _degraded_enforce(root, header, sections, budget)
        _write_sections(rope_path, header, sections)
        print(f"logged {args.section} (degraded mode)")
    elif args.command == "status":
        body = rope_path.read_text(encoding="utf-8")
        print(f"mode: degraded (no TurboVec)\nrope: {rope_path}")
        print(f"est_tokens: {_est_tokens(body)}\nbudget: {budget}")
    elif args.command in ("jump", "retire"):
        m = re.match(r"^(# ROPE v1 \| sess:\S+ \| j:)(\d+)( \| t:)\S+$", header)
        if m:
            header = f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}{_now()}"
        _degraded_enforce(root, header, sections, budget)
        _write_sections(rope_path, header, sections)
        sys.stdout.write(rope_path.read_text(encoding="utf-8"))
    elif args.command == "query":
        overflow = root / OVERFLOW_NAME
        hits: list[str] = []
        if overflow.exists():
            needle = args.text.lower()
            hits = [
                "RETRIEVED|" + ln.replace("|", "|", 1)
                for ln in overflow.read_text(encoding="utf-8").splitlines()
                if needle in ln.lower()
            ]
        print("\n".join(hits) if hits else "NO-HIT")
    return 0


# ------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rope_ops.py")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--root", default=".")
        p.add_argument("--budget", type=int, default=DEFAULT_BUDGET)

    common(sub.add_parser("init"))
    p_log = sub.add_parser("log")
    common(p_log)
    p_log.add_argument("section", choices=["state", "goal", "decision", "delta", "open"])
    p_log.add_argument("content")
    p_log.add_argument("--key", default=None)
    p_log.add_argument("--path", default=None)
    p_log.add_argument("--priority", type=int, default=2, choices=[0, 1, 2, 3])
    p_log.add_argument("--status", default="pending",
                       choices=["pending", "active", "done", "failed"])
    p_log.add_argument("--change-class", default="mod")
    p_log.add_argument("--reason", default="")
    common(sub.add_parser("status"))
    common(sub.add_parser("jump"))
    common(sub.add_parser("retire"))
    p_query = sub.add_parser("query")
    common(p_query)
    p_query.add_argument("text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if _full_mode_available():
        return _full(args)
    return _degraded(args)


if __name__ == "__main__":
    raise SystemExit(main())
