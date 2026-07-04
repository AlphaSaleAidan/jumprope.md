"""A2–A4 — starvation and floor attacks on the budget machinery."""

from __future__ import annotations

import random
from collections.abc import Callable
from pathlib import Path

import pytest

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.tokens import count_tokens

# A3 — empirically measured fixed floor (legend + header + anchors) is 155
# tokens under o200k_base. Pin at measured +10% so legend bloat regresses
# loudly, plus the spec's absolute cap.
FLOOR_PIN = 175
FLOOR_ABSOLUTE_CAP = 450


def test_a2_unsatisfiable_budget_fails_loudly_at_config_time(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    """A budget below the fixed floor must be rejected at construction with a
    computed minimum in the error — not by thrashing or corrupting the rope."""
    with pytest.raises(ValueError, match=r"minimum.*\d+"):
        JumpingRopeSession(
            tmp_path / "starved",
            session_id="starved",
            config=JumpConfig(rope_budget_tokens=100),
            force_fallback=True,
            clock=clock,
        )
    # Nothing half-initialized left on disk.
    assert not (tmp_path / "starved" / "session.json").exists()


def test_a2_budget_just_above_minimum_works(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = JumpingRopeSession(
        tmp_path / "ok",
        session_id="ok",
        config=JumpConfig(rope_budget_tokens=400),
        force_fallback=True,
        clock=clock,
    )
    session.record_event("open", "a modest event", priority=2)
    assert count_tokens(session.rope.render()) <= 400
    session.close()


def test_a3_fixed_floor_pinned(tmp_path: Path, clock: Callable[[], str]) -> None:
    """Absolute cap on the empty-rope floor — the guard the % ratio test
    cannot provide."""
    session = JumpingRopeSession(
        tmp_path / "floor",
        session_id="floor",
        force_fallback=True,
        clock=clock,
    )
    carried = session.jump()  # empty session, one jump
    floor = count_tokens(carried)
    print(f"\n[a3] measured empty-rope floor: {floor} tokens")
    assert floor <= FLOOR_PIN, f"floor grew to {floor} (> pinned {FLOOR_PIN})"
    assert floor <= FLOOR_ABSOLUTE_CAP
    session.close()


def test_a4_keyring_death_spiral(tmp_path: Path, clock: Callable[[], str]) -> None:
    """500 events at budget 600: KEYS stays bounded, TurboVec growth is
    linear, and no event content is lost."""
    rng = random.Random(42)
    adjectives = ["amber", "brisk", "coral", "dusky", "ember", "frost", "gilded",
                  "hollow", "ionic", "jasper", "kelp", "lunar", "mossy", "nickel"]
    nouns = ["anchor", "baffle", "crank", "dynamo", "eyelet", "flange", "gasket",
             "hinge", "impeller", "jig", "keel", "lattice", "manifold", "nozzle"]

    session = JumpingRopeSession(
        tmp_path / "spiral",
        session_id="spiral",
        config=JumpConfig(rope_budget_tokens=600),
        force_fallback=True,
        clock=clock,
    )
    events: list[str] = []
    max_keys_lines = 0
    for i in range(500):
        content = (
            f"event-{i:03d} the {adjectives[i % 14]} {nouns[(i * 7) % 14]} "
            f"requires recalibration of the {nouns[(i * 3 + 5) % 14]} assembly"
        )
        events.append(content)
        session.record_event("decision", content, reason="spiral", densify=False)
        assert count_tokens(session.rope.render()) <= 600, f"budget broken at {i}"
        max_keys_lines = max(max_keys_lines, len(session.rope.keys))

    stats = session.store.stats()
    records = int(stats["records"])  # type: ignore[call-overload]
    print(f"\n[a4] max KEYS lines: {max_keys_lines}, records: {records} for 500 events")

    # KEYS bounded at all times (coalescing keeps up).
    assert max_keys_lines <= 40, f"KEYS ballooned to {max_keys_lines} lines"
    # Linear, not quadratic: 500 demotions + keyring generations.
    assert records <= 2 * 500 + 50, f"{records} records for 500 events"

    # No content lost: 25 random events recoverable via semantic search.
    for i in rng.sample(range(500), 25):
        hits = session.store.search(events[i], k=3, session_id="spiral")
        assert any(f"event-{i:03d}" in h.content for h in hits), (
            f"event-{i:03d} unrecoverable via search"
        )
    session.close()
