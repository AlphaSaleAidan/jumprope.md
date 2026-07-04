"""Phase 5 — replay a REAL Claude Code session through the regimes.

A `.jsonl` session log is turned into the same shape the synthetic bench
uses: a turn stream plus probes with owned ground truth. Probes are mined
by *cloze* — we find distinctive tokens the session states once (a port, a
hash, a flag name, a file path, a number) and later ask for them back,
scoring by exact-substring match. No LLM judge, no hand-labeling.

The loader is content-agnostic. A `redact` option keeps raw session text
out of committed artifacts (only tags + hit/miss), so real logs can be
benchmarked without leaking their contents.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .scenario import Event, Probe, Scenario

# Distinctive value shapes worth asking about later: they are specific,
# unlikely to be guessed, and cheap to score by exact match.
# Ordered most-specific first; each match claims its span so a later, broader
# pattern cannot re-mine the same characters (avoids a hash also matching the
# generic-hex rule, or "3.10.4" also yielding "10.4").
_VALUE_PATTERNS = [
    re.compile(r"\b(tv-[0-9a-f]{8,})\b"),
    re.compile(r"\b([A-Z][A-Z0-9]{2,}_[A-Z0-9_]{2,})\b"),  # ENV_STYLE_FLAGS
    re.compile(r"\bport\s+(\d{2,5})\b", re.I),
    re.compile(r"\b(?:PR|issue)\s*#?(\d{2,5})\b", re.I),
    re.compile(r"#(\d{2,5})\b"),
    re.compile(r"\bv?(\d+\.\d+\.\d+(?:\.\d+)?)\b"),  # semantic versions
    re.compile(r"\b([0-9a-f]{7,40})\b"),  # bare git shas
    re.compile(r"`([a-z][a-z0-9_\-/]{4,}\.[a-z]{1,4})`"),  # file paths in ticks
]
_STOPVALUES = {"http", "https", "20", "200", "404", "100", "000"}


def _message_text(obj: dict[str, object]) -> tuple[str, str]:
    # Bench schema: {"role", "content"} at top level.
    if "role" in obj and "content" in obj and "message" not in obj:
        content = obj["content"]
        return str(obj["role"]), content if isinstance(content, str) else ""
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return "", ""
    role = str(msg.get("role", ""))
    content = msg.get("content", "")
    if isinstance(content, str):
        return role, content
    if isinstance(content, list):
        parts = [
            str(p.get("text", ""))
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        return role, "\n".join(parts)
    return role, ""


@dataclass
class TranscriptStats:
    total_messages: int = 0
    turns_kept: int = 0
    probes: int = 0
    unique_values: int = 0
    dropped_ambiguous: int = 0
    redacted: bool = False


@dataclass
class LoadedTranscript:
    scenario: Scenario
    stats: TranscriptStats = field(default_factory=TranscriptStats)


def _extract_values(text: str) -> set[str]:
    values: set[str] = set()
    claimed: list[tuple[int, int]] = []  # spans already taken by a better pattern
    for pattern in _VALUE_PATTERNS:
        for match in pattern.finditer(text):
            lo, hi = match.span(1)
            if any(lo < c_hi and hi > c_lo for c_lo, c_hi in claimed):
                continue  # overlaps an already-mined, more specific value
            val = match.group(1)
            if val.lower() not in _STOPVALUES and len(val) >= 2:
                values.add(val)
                claimed.append((lo, hi))
    return values


def _clause_around(text: str, value: str) -> str:
    """A short natural-language window around ``value`` — the fact line."""
    idx = text.find(value)
    lo = max(0, idx - 70)
    hi = min(len(text), idx + len(value) + 40)
    snippet = text[lo:hi].replace("\n", " ").strip()
    return re.sub(r"\s+", " ", snippet)


def load(
    path: str | Path,
    max_turns: int = 120,
    min_probe_distance: int = 6,
    redact: bool = False,
) -> LoadedTranscript:
    """Parse a Claude Code `.jsonl` into a replayable Scenario with probes."""
    stats = TranscriptStats(redacted=redact)
    turns: list[list[Event]] = []
    # First value-occurrence: (turn_index, distinctive value, fact clause).
    first_seen: dict[str, tuple[int, str]] = {}
    value_counts: Counter[str] = Counter()

    for raw in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        if len(turns) >= max_turns:
            break
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        # Accept Claude Code rows (type user/assistant) and bench-schema rows
        # (top-level role, no type).
        is_bench_row = "role" in obj and "type" not in obj
        if not is_bench_row and obj.get("type") not in ("user", "assistant"):
            continue
        role, text = _message_text(obj)
        stats.total_messages += 1
        text = text.strip()
        # Skip system-injected/tool noise and trivially short lines.
        if not text or text.startswith(("<", "[Request", "Caveat:")) or len(text) < 25:
            continue
        turn_idx = len(turns)
        turns.append([Event(kind="turn", text=text, rope_section="open",
                            rope_kwargs={"priority": 2})])
        stats.turns_kept += 1
        for value in _extract_values(text):
            value_counts[value] += 1
            if value not in first_seen:
                first_seen[value] = (turn_idx, _clause_around(text, value))

    # A value is probe-worthy if it appears at least twice (so it is a real
    # recurring fact, not a one-off) and reads distinctively.
    probes: list[Probe] = []
    n_turns = len(turns)
    for value, (ref_turn, clause) in sorted(first_seen.items(), key=lambda kv: kv[1][0]):
        if value_counts[value] < 2:
            continue
        probe_turn = min(ref_turn + min_probe_distance + (len(probes) % 20), n_turns - 1)
        if probe_turn <= ref_turn:
            stats.dropped_ambiguous += 1
            continue
        subject = clause if not redact else f"[fact #{len(probes) + 1}]"
        probes.append(
            Probe(
                turn=probe_turn,
                kind="fact",
                tag=f"T{len(probes) + 1:02d}",
                question=(
                    f"Earlier in this session, what value went with: "
                    f"\"{subject}\"? Answer with the exact token."
                ),
                expected_any=(value,),
                ref_turn=ref_turn,
            )
        )

    stats.probes = len(probes)
    stats.unique_values = len(first_seen)
    probes.sort(key=lambda p: p.turn)
    scenario = Scenario(seed=-1, n_turns=n_turns, turns=turns, probes=probes)
    return LoadedTranscript(scenario=scenario, stats=stats)
