"""§8.1 — Rope spec round-trip: build → render → parse → identical structure."""

from __future__ import annotations

import pytest

from jumping_rope.notation import get_profile
from jumping_rope.rope import RopeFile, RopeParseError


def build_rope() -> RopeFile:
    rope = RopeFile.new(
        session_id="rt-test", timestamp="2026-07-03T12:00:00Z",
        legend=get_profile("symbolic-en").legend(),
    )
    rope.set_state("cwd", "/srv/app")
    rope.set_state("branch", "feat/x")
    rope.add_goal("ship parser", status="active")
    rope.add_goal("write docs", status="pending")
    rope.add_decision("2026-07-01", "use sqlite-vec", "zero server")
    rope.add_decision("2026-07-02", "hash embedder for CI", "deterministic")
    rope.add_delta("src/rope.py", "add", "parser + renderer")
    rope.add_delta("tests/test_rope.py", "add", "12 cases")
    rope.add_open("flaky CI on 3.12", priority=1)
    rope.add_open("rename module?", priority=3)
    rope.add_key("early design notes", "tv-abc123")
    return rope


def test_roundtrip_identical() -> None:
    rope = build_rope()
    rendered = rope.render()
    parsed = RopeFile.parse(rendered)
    assert parsed == rope
    assert parsed.render() == rendered  # render is a fixed point


def test_roundtrip_after_mutations() -> None:
    rope = build_rope()
    rope.set_goal_status(1, "done")
    rope.add_delta("src/rope.py", "mod", "fix parser edge")  # replaces entry
    assert len([d for d in rope.delta if d.path == "src/rope.py"]) == 1
    parsed = RopeFile.parse(rope.render())
    assert parsed == rope
    assert parsed.goals[0].status == "✓"


def test_field_sanitization_roundtrips() -> None:
    rope = build_rope()
    rope.add_open("text with | pipe\nand newline", priority=2)
    parsed = RopeFile.parse(rope.render())
    assert parsed == rope
    assert parsed.open_items[-1].text == "text with / pipe; and newline"


def test_validate_accepts_good_rope() -> None:
    build_rope().validate()


@pytest.mark.parametrize(
    "mutant",
    [
        "not a rope",
        "# ROPE v2 | sess:x | j:0 | t:now",
        "# ROPE v1 | sess:x | j:0 | t:t\n## LEGEND\n## STATE\n## GOALS",
        "# ROPE v1 | sess:x | j:0 | t:t\n## BOGUS\n",
    ],
)
def test_parse_rejects_malformed(mutant: str) -> None:
    with pytest.raises(RopeParseError):
        RopeFile.parse(mutant)


def test_parse_rejects_blank_line_padding() -> None:
    rendered = build_rope().render().replace("## STATE", "\n## STATE", 1)
    with pytest.raises(RopeParseError):
        RopeFile.parse(rendered)
