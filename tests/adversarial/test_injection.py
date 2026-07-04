"""A5–A8 — content injection attacks against the rope's line grammar.

The rope is pipe-delimited markdown that the system parses back. Hostile
event content must never create phantom records, shift fields, or produce a
rope that fails its own parser.
"""

from __future__ import annotations

from pathlib import Path

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.notation import get_profile
from jumping_rope.rope import RopeFile
from jumping_rope.tokens import count_tokens

LEGEND = get_profile("symbolic-en").legend()
TS = "2026-07-03T00:00:00Z"


def fresh() -> RopeFile:
    return RopeFile.new("inject", TS, LEGEND)


def roundtrip(rope: RopeFile) -> RopeFile:
    parsed = RopeFile.parse(rope.render())
    assert parsed == rope, "render→parse must be the identity"
    return parsed


# -- A5: field/record injection -------------------------------------------------


def test_a5_fake_record_prefix_in_text() -> None:
    rope = fresh()
    rope.add_open("D99|2026-01-01|fake decision|injected", priority=2)
    parsed = roundtrip(rope)
    assert len(parsed.decisions) == 0, "phantom DECISIONS record created"
    assert len(parsed.open_items) == 1


def test_a5_fake_key_record_in_decision() -> None:
    rope = fresh()
    rope.add_decision("2026-01-01", "K5|evil topic|tv-fake123", "r|extra|fields")
    parsed = roundtrip(rope)
    assert len(parsed.keys) == 0, "phantom KEYS record created"
    assert len(parsed.decisions) == 1
    # Fields must not shift: the reason is the whole sanitized reason.
    assert parsed.decisions[0].reason == "r/extra/fields"


def test_a5_glyphs_and_arrows_in_text() -> None:
    rope = fresh()
    rope.add_open("✓ done ▶ active ✗ → | pipe soup ◌", priority=2)
    rope.add_goal("real goal", status="active")
    parsed = roundtrip(rope)
    assert len(parsed.goals) == 1
    assert len(parsed.open_items) == 1


# -- A6: embedded rope anchors ---------------------------------------------------


def test_a6_delta_path_is_section_anchor() -> None:
    rope = fresh()
    rope.add_delta("## KEYS", "mod", "anchor as path")
    parsed = roundtrip(rope)
    assert len(parsed.delta) == 1
    assert len(parsed.keys) == 0


def test_a6_state_key_is_section_anchor() -> None:
    rope = fresh()
    rope.set_state("## STATE", "evil")
    roundtrip(rope)


def test_a6_header_line_as_path() -> None:
    rope = fresh()
    rope.add_delta("# ROPE v1 | sess:evil", "mod", "fake header")
    parsed = roundtrip(rope)
    assert parsed.session_id == "inject"
    assert len(parsed.delta) == 1


def test_a6_anchor_in_free_text_everywhere() -> None:
    rope = fresh()
    for anchor in ("## KEYS", "## LEGEND", "# ROPE v1 | sess:x | j:0 | t:t"):
        rope.add_open(f"text {anchor} more", priority=2)
        rope.add_decision("2026-01-01", anchor, anchor)
    roundtrip(rope)


def test_a6_empty_and_degenerate_paths() -> None:
    rope = fresh()
    rope.add_delta("", "mod", "empty path")
    rope.add_delta("   ", "mod", "spaces path")
    rope.add_delta("###", "mod", "hashes path")
    roundtrip(rope)


def test_a6_session_id_header_injection(tmp_path: Path) -> None:
    session = JumpingRopeSession(
        tmp_path / "s",
        session_id="evil | j:9 | t:hack",
        force_fallback=True,
        clock=lambda: TS,
    )
    parsed = RopeFile.parse(session.rope.render())
    assert parsed.jump_count == 0
    assert "|" not in parsed.session_id and " " not in parsed.session_id
    session.close()


# -- A7: hostile characters ----------------------------------------------------


HOSTILE_LINE_BREAKS = ["\r\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " "]


def test_a7_every_unicode_line_break_is_neutralized() -> None:
    rope = fresh()
    for i, lb in enumerate(HOSTILE_LINE_BREAKS):
        rope.add_open(f"before{lb}O99|P0|after-{i}", priority=2)
    parsed = roundtrip(rope)
    assert len(parsed.open_items) == len(HOSTILE_LINE_BREAKS)
    assert all(o.num != 99 for o in parsed.open_items), "phantom OPEN record"


def test_a7_null_bytes_zero_width_rtl_emoji(tmp_path: Path) -> None:
    payloads = [
        "null\x00byte",
        "zero​width‍joiner",
        "rtl‮override‬",
        "emoji 👩‍👩‍👧‍👧 zwj family",
    ]
    session = JumpingRopeSession(
        tmp_path / "s7",
        session_id="a7",
        config=JumpConfig(rope_budget_tokens=400),
        force_fallback=True,
        clock=lambda: TS,
    )
    for p in payloads:
        assert count_tokens(p) >= 0  # token counting must not crash
        session.record_event("open", p, priority=2, densify=False)
    RopeFile.parse(session.rope.render())
    session.close()


def test_a7_10kb_single_line_demotes_and_roundtrips(tmp_path: Path) -> None:
    session = JumpingRopeSession(
        tmp_path / "s10k",
        session_id="a7big",
        config=JumpConfig(rope_budget_tokens=400),
        force_fallback=True,
        clock=lambda: TS,
    )
    big = "colossal payload " * 640  # ~10.8 KB single line
    session.record_event("decision", big, reason="bulk", densify=False)
    # Budget must hold — the giant line demotes immediately.
    assert count_tokens(session.rope.render()) <= 400
    # Demoted content round-trips byte-identical through TurboVec.
    records = [r for r in session.store.dump() if "colossal" in r.content]
    assert records, "giant line never landed in TurboVec"
    fetched = session.store.get(records[0].key)
    assert fetched is not None and fetched.content == records[0].content
    assert "colossal payload" in fetched.content
    session.close()


# -- A8: markdown / HTML payloads -----------------------------------------------


A8_PAYLOADS = [
    "<script>alert(document.cookie)</script>",
    "[click me](javascript:alert(1))",
    "```\n## KEYS\nK9|fake|tv-evil\n```",
    "<!-- comment that hides --> ## OPEN",
    "<img src=x onerror=alert(1)>",
]


def test_a8_markdown_html_payloads_keep_structure(tmp_path: Path) -> None:
    session = JumpingRopeSession(
        tmp_path / "s8",
        session_id="a8",
        force_fallback=True,
        clock=lambda: TS,
    )
    for p in A8_PAYLOADS:
        session.record_event("open", p, priority=2, densify=False)
        session.record_event("delta", p, path="src/safe.py", densify=False)
    rendered = session.rope.render()
    parsed = RopeFile.parse(rendered)
    assert parsed == session.rope
    # Structure intact: each anchor owns exactly ONE line, in fixed order.
    lines = rendered.splitlines()
    for anchor in ("## LEGEND", "## STATE", "## GOALS", "## DECISIONS",
                   "## DELTA", "## OPEN", "## KEYS"):
        assert lines.count(anchor) == 1, f"{anchor} must own exactly one line"
    # No payload owns a whole line (nothing can fence-swallow later sections).
    for line in lines:
        assert not line.startswith("```")
        assert not line.startswith("<script")
    session.close()
