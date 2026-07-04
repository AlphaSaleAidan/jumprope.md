"""§8.2 — Budget enforcement over 200 synthetic events."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.tokens import count_tokens

BUDGET = 600  # small enough to force many demotions across 200 events


def make_session(tmp_path: Path, clock: Callable[[], str]) -> JumpingRopeSession:
    return JumpingRopeSession(
        tmp_path / "s",
        session_id="budget-test",
        config=JumpConfig(rope_budget_tokens=BUDGET),
        force_fallback=True,
        clock=clock,
    )


def test_budget_enforced_after_every_write(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = make_session(tmp_path, clock)
    session.record_event("state", "/srv/app", key="cwd")
    session.record_event("goal", "keep rope under budget forever", status="active")
    protected_state = dict(session.rope.state)
    protected_goals = [g.render() for g in session.rope.goals]
    legend = session.rope.legend

    kinds = ("decision", "delta", "open")
    for i in range(200):
        kind = kinds[i % 3]
        content = (
            f"synthetic event number {i}: the module was refactored because the "
            f"previous implementation of feature {i} was really quite slow"
        )
        if kind == "delta":
            session.record_event(kind, content, path=f"src/mod_{i}.py")
        elif kind == "open":
            session.record_event(kind, content, priority=2 + (i % 2))  # P2/P3
        else:
            session.record_event(kind, content, reason=f"perf issue {i}")

        # THE invariant: rope fits budget after every single write.
        rendered = session.rope.render()
        assert count_tokens(rendered) <= BUDGET, f"over budget after event {i}"
        # Never-demoted sections intact.
        assert session.rope.legend == legend
        assert session.rope.state == protected_state
        assert [g.render() for g in session.rope.goals] == protected_goals

    stats = session.store.stats()
    assert isinstance(stats["records"], int) and stats["records"] > 100
    session.close()


def test_demotion_order_decisions_then_delta_then_open(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = make_session(tmp_path, clock)
    filler = "a distinctly verbose description that occupies a good number of tokens "
    for i in range(3):
        session.record_event("decision", f"decision {i} " + filler, reason="r")
    for i in range(3):
        session.record_event("delta", f"delta {i} " + filler, path=f"f{i}.py")
    session.record_event("open", "open p3 " + filler, priority=3)
    session.record_event("open", "open p2 " + filler, priority=2)
    session.record_event("open", "open p0 keep me", priority=0)

    demotions = []
    while True:
        d = session.compactor.demote_one(session.rope)
        if d is None:
            break
        demotions.append(d)
    sections = [d.section for d in demotions]
    # Oldest-first within DECISIONS, then DELTA, then OPEN (P3 before P2).
    assert sections == ["DECISIONS"] * 3 + ["DELTA"] * 3 + ["OPEN", "OPEN"]
    assert "decision 0" in demotions[0].content
    assert "decision 1" in demotions[1].content
    assert "delta 0" in demotions[3].content
    assert "p3" in demotions[6].content
    assert "p2" in demotions[7].content
    # P0/P1 OPEN items are never demotable.
    assert [o.priority for o in session.rope.open_items] == [0]
    session.close()


def test_open_p0_p1_survive_extreme_pressure(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = make_session(tmp_path, clock)
    session.record_event("open", "P0 fact: prod db password rotates friday", priority=0)
    session.record_event("open", "P1 fact: release gate needs legal signoff", priority=1)
    for i in range(60):
        session.record_event(
            "decision",
            f"noise decision {i} with plenty of surrounding verbosity to force demotion",
            reason="noise",
        )
    texts = [o.text for o in session.rope.open_items]
    assert any("P0 fact" in t for t in texts)
    assert any("P1 fact" in t for t in texts)
    session.close()
