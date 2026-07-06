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
current workspace. When the per-session convention is in use
(`.claude/jumprope/sessions/<session_id>/ROPE.md`, as created by the
`/jumprope-start` command from adapters/claude-commands), each session sees
only its own rope — concurrent sessions never share a gauge. Otherwise the
freshest ROPE.md under the workspace is used, as before.

Config, lowest to highest precedence: built-in defaults, an `env` file of
KEY=VALUE lines next to the rope (`.claude/jumprope/env` and the session
dir's `env`), then real environment variables:

  JROPE_ROPE_PATH  force a specific rope file
  JROPE_BUDGET     bound-mode token budget (default 2000)
  JROPE_MODE       "unbound" for the ∞ readout (default bound)
  JROPE_EMOJI      gauge glyph (default 🪢)
  JROPE_ANIMATE    "0" disables the rope-swing animation (default on)
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
# rotating stroke = the rope whipping around; refreshes only happen while
# the session is active, so the rope visibly spins while working
SPIN = "|/─\\"
_BRAILLE_BITS = {(0, 0): 1, (0, 1): 2, (0, 2): 4, (1, 0): 8,
                 (1, 1): 16, (1, 2): 32, (0, 3): 64, (1, 3): 128}


def _rope_frames(n: int = 12, w: int = 8, h: int = 4,
                 amp: float = 2.4) -> tuple[str, ...]:
    """JROPE_STYLE=drawn: a custom-drawn rope, no holder.

    Braille chars are 2x4 pixel grids, so 4 chars give an 8x4 canvas. Each
    frame plots the rope's curve y = sin(pi*x/w)*cos(theta) — the front view
    of a real jump-rope swing: arc over the top, whip past level, arc under
    the feet, back past level. Adjacent columns are connected so the rope
    stays one continuous line.
    """
    frames = []
    mid = (h - 1) / 2
    for k in range(n):
        theta = 2 * math.pi * k / n
        ys = [min(h - 1, max(0, round(
            mid - amp * math.sin(math.pi * (x + 0.5) / w) * math.cos(theta))))
            for x in range(w)]
        cells = [0] * (w // 2)
        for x in range(w):
            lo = ys[x] if x == 0 else min(ys[x - 1], ys[x])
            hi = ys[x] if x == 0 else max(ys[x - 1], ys[x])
            for y in range(lo, hi + 1):
                cells[x // 2] |= _BRAILLE_BITS[(x % 2, y)]
        frames.append("".join(chr(0x2800 + c) for c in cells))
    return tuple(frames)


ROPE_FRAMES = _rope_frames()
ROPE_SLACK = "⣀⣀⣀⣀"  # limp rope on the ground: nothing is swinging it yet
DEFAULTS = {"JROPE_BUDGET": "2000", "JROPE_MODE": "bound",
            "JROPE_EMOJI": "🪢", "JROPE_ANIMATE": "1", "JROPE_STYLE": "emoji"}


def _read_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _cwd(info: dict) -> str:
    ws = info.get("workspace") or {}
    return (ws.get("project_dir") or ws.get("current_dir")
            or info.get("cwd") or os.getcwd())


def _sessions_root(cwd: str) -> str:
    return os.path.join(cwd, ".claude", "jumprope", "sessions")


def _find_rope(cwd: str, session_id: str | None = None) -> str | None:
    override = os.environ.get("JROPE_ROPE_PATH")
    if override and os.path.exists(override):
        return override
    if session_id:
        scoped = os.path.join(_sessions_root(cwd), session_id, "ROPE.md")
        if os.path.isfile(scoped):
            return scoped
    if os.path.isdir(_sessions_root(cwd)):
        return None  # per-session convention active: never show another session's rope
    candidates: list[str] = []
    for pat in ("ROPE.md", ".jumprope/**/ROPE.md", ".claude/jumprope/**/ROPE.md",
                ".jumprope/ROPE.md", "**/ROPE.md"):
        candidates += glob.glob(os.path.join(cwd, pat), recursive=True)
    candidates = [c for c in candidates if os.path.isfile(c)]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)  # freshest rope


def _file_cfg(cwd: str, session_id: str | None) -> dict[str, str]:
    """KEY=VALUE `env` files: repo-wide, then per-session (later wins)."""
    cfg: dict[str, str] = {}
    paths = [os.path.join(cwd, ".claude", "jumprope", "env")]
    if session_id:
        paths.append(os.path.join(_sessions_root(cwd), session_id, "env"))
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            for ln in open(path, encoding="utf-8"):
                ln = ln.strip()
                if ln and not ln.startswith("#") and "=" in ln:
                    key, val = ln.split("=", 1)
                    cfg[key.strip()] = val.strip()
        except OSError:
            pass
    return cfg


def _opt(name: str, cfg: dict[str, str]) -> str:
    return os.environ.get(name) or cfg.get(name) or DEFAULTS[name]


def _est_tokens(text: str) -> int:
    # cheap, dependency-free estimate (~4 chars/token) — good enough for a gauge.
    return max(1, round(len(text) / 4))


def _parse_meta(text: str) -> int:
    """Return the jump count sniffed from the rope header if present."""
    jumps = 0
    first = text.split("\n", 1)[0]
    for tok in first.replace("|", " ").split():
        if tok.startswith("j:"):
            try:
                jumps = int(tok[2:])
            except ValueError:
                pass
    return jumps


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
HOT = "\x1b[38;2;235;242;255m"  # white-hot: a write just landed
FLASH_S = 6.0  # how long a write stays visibly flagged


def _write_flash(rope: str, tokens: int, now: float) -> tuple[int, bool]:
    """Detect rope growth between refreshes: (delta, fresh).

    A tiny state file beside the rope remembers the last seen size. When the
    size changes, the delta is flagged for FLASH_S seconds — the gauge shows
    a bright +N and burns the bar's leading cell white, so every write is
    visible even when the fill moves less than one cell.
    """
    state_path = os.path.join(os.path.dirname(rope), ".gauge-state")
    prev = None
    try:
        prev = json.load(open(state_path, encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if prev is None:
        prev = {"size": tokens, "ts": 0.0, "delta": 0}  # first sight: no flash
    elif tokens != prev.get("size"):
        prev = {"size": tokens, "ts": now, "delta": tokens - int(prev.get("size", tokens))}
    else:
        fresh = prev.get("delta", 0) != 0 and (now - prev.get("ts", 0)) < FLASH_S
        return int(prev.get("delta", 0)), fresh
    try:
        json.dump(prev, open(state_path, "w", encoding="utf-8"))
    except OSError:
        pass
    fresh = prev["delta"] != 0 and (now - prev["ts"]) < FLASH_S
    return int(prev["delta"]), fresh


def _human(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


def render(info: dict, now: float | None = None) -> str:
    now = time.time() if now is None else now
    cwd = _cwd(info)
    sid = info.get("session_id")
    cfg = _file_cfg(cwd, sid)
    emoji = _opt("JROPE_EMOJI", cfg)
    animate = _opt("JROPE_ANIMATE", cfg) != "0"
    drawn = _opt("JROPE_STYLE", cfg).lower() == "drawn"
    idle = ROPE_SLACK if drawn else emoji

    def lead(col: str) -> str:
        """The gauge glyph: emoji+stroke, or the drawn rope mid-swing."""
        if drawn:
            frame = ROPE_FRAMES[int(now * 12) % len(ROPE_FRAMES)] if animate \
                else ROPE_FRAMES[0]
            return f"{col}{frame}{RESET}"
        return emoji + (SPIN[int(now * 8) % len(SPIN)] if animate else "")

    rope = _find_rope(cwd, sid)
    if rope is None:
        hint = ("no rope — /jumprope-start"
                if os.path.isdir(_sessions_root(cwd)) else "no rope yet")
        return f"{DIM}{idle} {hint}{RESET}"
    try:
        text = open(rope, encoding="utf-8", errors="ignore").read()
    except OSError:
        return f"{DIM}{idle} rope unreadable{RESET}"
    tokens = _est_tokens(text)
    jumps = _parse_meta(text)
    unbound = _opt("JROPE_MODE", cfg).lower() == "unbound"
    budget = int(_opt("JROPE_BUDGET", cfg))
    delta, fresh = _write_flash(rope, tokens, now)
    tick = f" {HOT}{'+' if delta > 0 else ''}{delta}{RESET}" if fresh else ""

    if unbound:
        # no ceiling — scale color by absolute size tiers, gentle pulse
        fill = min(1.0, tokens / 8000)
        base = _fill_color(fill)
        b = _pulse(fill * 0.6, now)
        col = _ansi(tuple(round(c * b) for c in base))
        return (f"{lead(col)}{col} {_human(tokens)} tok ∞{RESET}{tick} "
                f"{DIM}unbound · j{jumps}{RESET}")

    fill = tokens / budget
    filled = min(BAR_W, round(min(fill, 1.0) * BAR_W))
    base = _fill_color(fill)
    b = _pulse(min(fill, 1.05), now)
    col = _ansi(tuple(round(c * b) for c in base))
    if fresh and filled > 0:
        # the newest cell burns white while the write is fresh
        bar = (col + FILLED * (filled - 1) + HOT + FILLED
               + DIM + EMPTY * (BAR_W - filled) + RESET)
    else:
        bar = col + FILLED * filled + DIM + EMPTY * (BAR_W - filled) + RESET
    over = f" {_ansi((239,68,68))}JUMP!{RESET}" if fill >= 1.0 else ""
    pct = f"{col}{min(fill,1.0)*100:.0f}%{RESET}"
    return (f"{lead(col)} {bar} {col}{_human(tokens)}{RESET}{DIM}/{_human(budget)}{RESET} "
            f"{pct}{over}{tick} {DIM}j{jumps}{RESET}")


if __name__ == "__main__":
    print(render(_read_stdin_json()))
