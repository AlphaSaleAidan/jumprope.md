"""§8.10 — Reasoner-profile sanity: the properties that keep the rope cheap
for long-context reasoning models (DeepSeek-V4-class targets).

- the legend appears exactly once
- no blank-line padding anywhere
- stable section anchors, fixed order
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.rope import SECTIONS


def build_busy_rope(tmp_path: Path, clock: Callable[[], str]) -> str:
    session = JumpingRopeSession(
        tmp_path / "sanity",
        session_id="sanity",
        config=JumpConfig(rope_budget_tokens=800, jump_every_n_turns=4),
        force_fallback=True,
        clock=clock,
    )
    session.record_event("state", "/srv/sanity", key="cwd")
    session.record_event("goal", "stay cheap for reasoners", status="active")
    for i in range(40):
        session.record_event(
            "decision", f"decision {i} with a moderately verbose justification attached",
            reason="testing",
        )
        session.note_turn(f"turn {i}")
        if session.should_jump():
            session.jump()
    text = session.jump()
    session.close()
    return text


def test_legend_never_repeated(tmp_path: Path, clock: Callable[[], str]) -> None:
    text = build_busy_rope(tmp_path, clock)
    assert text.count("## LEGEND") == 1
    # The legend's first line occurs exactly once in the entire rope.
    legend_first_line = "glyphs: ✓done ▶active"
    assert text.count(legend_first_line) == 1


def test_no_blank_line_padding(tmp_path: Path, clock: Callable[[], str]) -> None:
    text = build_busy_rope(tmp_path, clock)
    assert "\n\n" not in text
    assert not text.startswith("\n")
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_stable_anchors_fixed_order(tmp_path: Path, clock: Callable[[], str]) -> None:
    text = build_busy_rope(tmp_path, clock)
    positions = [text.find(f"## {name}") for name in SECTIONS]
    assert all(p >= 0 for p in positions), "every anchor present"
    assert positions == sorted(positions), "anchors in fixed spec order"
    # Anchors are exact — no decorated variants.
    for name in SECTIONS:
        assert text.count(f"## {name}") == 1


def test_header_is_single_line_machine_parseable(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    text = build_busy_rope(tmp_path, clock)
    header = text.splitlines()[0]
    assert header.startswith("# ROPE v1 | sess:sanity | j:")
    assert " t:" in header
