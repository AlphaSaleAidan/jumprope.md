#!/usr/bin/env python3
"""Claude Code statusline: a live rope gauge.

Renders a one-line gauge of how full the Jumping Rope ledger is. As the rope
fills toward its token budget the bar shifts **warmer** (green → amber → red)
*and* its pulse gets **faster** — a calm breathing green when there's headroom,
a fast red flicker when it's about to jump. Pure stdlib, no imports of the
jumping_rope package, so it stays fast enough to run on every statusline refresh.

Wire it up (settings.json):

    { "statusLine": { "type": "command",
        "command": "python3 /abs/path/adapters/claude-statusline/statusline.py" } }

Claude Code pipes session JSON on stdin; we use it to find the rope for the
current workspace. Override the rope path with JROPE_ROPE_PATH, the budget with
JROPE_BUDGET (default 2000; ignored in unbound mode).
"""

from __future__ import annotations

import glob
import json
import math
import os
import sys
import time

BAR_W = 14
FILLED, EMPTY = "█", "░"


def _read_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _cwd(info: dict) -> str:
    ws = info.get("workspace") or {}
    return (ws.get("current_dir") or info.get("cwd") or os.getcwd())


def _find_rope(cwd: str) -> str | None:
    override = os.environ.get("JROPE_ROPE_PATH")
    if override and os.path.exists(override):
        return override
    candidates: list[str] = []
    for pat in ("ROPE.md", ".jumprope/**/ROPE.md", ".claude/jumprope/**/ROPE.md",
                ".jumprope/ROPE.md", "**/ROPE.md"):
        candidates += glob.glob(os.path.join(cwd, pat), recursive=True)
    candidates = [c for c in candidates if os.path.isfile(c)]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)  # freshest rope


def _est_tokens(text: str) -> int:
    # cheap, dependency-free estimate (~4 chars/token) — good enough for a gauge.
    return max(1, round(len(text) / 4))


def _parse_meta(text: str) -> tuple[int, bool]:
    """Return (jump_count, unbound) sniffed from the rope header if present."""
    jumps, unbound = 0, False
    first = text.split("\n", 1)[0]
    for tok in first.replace("|", " ").split():
        if tok.startswith("j:"):
            try:
                jumps = int(tok[2:])
            except ValueError:
                pass
    unbound = os.environ.get("JROPE_MODE", "").lower() == "unbound"
    return jumps, unbound


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _fill_color(fill: float) -> tuple[int, int, int]:
    # green → yellow → orange → red across [0,1]
    stops = [(0.0, (52, 211, 153)), (0.5, (245, 200, 66)),
             (0.78, (245, 158, 11)), (1.0, (239, 68, 68))]
    fill = max(0.0, min(1.0, fill))
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if fill <= t1:
            return _lerp(c0, c1, (fill - t0) / (t1 - t0) if t1 > t0 else 0)
    return stops[-1][1]


def _pulse(fill: float, now: float) -> float:
    # brightness 0.62..1.0; frequency grows with fill → "faster as it works harder"
    freq = 1.1 + fill * 7.5
    return 0.62 + 0.38 * (0.5 + 0.5 * math.sin(now * freq))


def _ansi(rgb: tuple[int, int, int]) -> str:
    return f"\x1b[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


RESET = "\x1b[0m"
DIM = "\x1b[38;2;74;95;134m"


def _human(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


def render(info: dict, now: float | None = None) -> str:
    now = time.time() if now is None else now
    rope = _find_rope(_cwd(info))
    if rope is None:
        return f"{DIM}🪢 no rope yet{RESET}"
    try:
        text = open(rope, encoding="utf-8", errors="ignore").read()
    except OSError:
        return f"{DIM}🪢 rope unreadable{RESET}"
    tokens = _est_tokens(text)
    jumps, unbound = _parse_meta(text)
    budget = int(os.environ.get("JROPE_BUDGET", "2000"))

    if unbound:
        # no ceiling — scale color by absolute size tiers, gentle pulse
        fill = min(1.0, tokens / 8000)
        base = _fill_color(fill)
        b = _pulse(fill * 0.6, now)
        col = _ansi(tuple(round(c * b) for c in base))
        return (f"{col}🪢 {_human(tokens)} tok ∞{RESET} "
                f"{DIM}unbound · j{jumps}{RESET}")

    fill = tokens / budget
    filled = min(BAR_W, round(min(fill, 1.0) * BAR_W))
    base = _fill_color(fill)
    b = _pulse(min(fill, 1.05), now)
    col = _ansi(tuple(round(c * b) for c in base))
    bar = col + FILLED * filled + DIM + EMPTY * (BAR_W - filled) + RESET
    over = f" {_ansi((239,68,68))}JUMP!{RESET}" if fill >= 1.0 else ""
    pct = f"{col}{min(fill,1.0)*100:.0f}%{RESET}"
    return (f"🪢 {bar} {col}{_human(tokens)}{RESET}{DIM}/{_human(budget)}{RESET} "
            f"{pct}{over} {DIM}j{jumps}{RESET}")


if __name__ == "__main__":
    print(render(_read_stdin_json()))
