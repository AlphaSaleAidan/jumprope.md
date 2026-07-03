"""§8.4 — Jump correctness (the money test).

30-turn simulated session, 12 planted facts, ≥3 jumps. After the final jump
the context is reconstructed from the rope ALONE; every P0/P1 fact must be in
the rope verbatim-or-stubbed, and every demoted fact must come back from
TurboVec both by exact key and by semantic search (top-3, HashEmbedder).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.rope import RopeFile
from jumping_rope.tokens import count_tokens

# (tag, distinctive text, section, priority) — tags survive densification.
CRITICAL_FACTS = [
    ("FACT-01", "FACT-01 prod postgres password rotates friday 17:00 UTC", 0),
    ("FACT-02", "FACT-02 legal signoff gates the quarterly release train", 1),
    ("FACT-03", "FACT-03 customer acme pinned to api v2 until 2027", 0),
    ("FACT-04", "FACT-04 payment webhooks replay from kafka topic billing-events", 1),
]
DEMOTABLE_FACTS = [
    ("FACT-05", "FACT-05 walrus schema stores tungsten keys in namespace omega", "decision"),
    ("FACT-06", "FACT-06 the heron cache evicts quartz entries after nine minutes", "decision"),
    ("FACT-07", "FACT-07 falcon queue drains into the basalt warehouse nightly", "decision"),
    ("FACT-08", "FACT-08 the juniper endpoint requires a cobalt bearer token", "delta"),
    ("FACT-09", "FACT-09 marble reports aggregate by fortnight not by month", "delta"),
    ("FACT-10", "FACT-10 the osprey worker retries exactly seven times with jitter", "delta"),
    ("FACT-11", "FACT-11 garnet tenants shard by postal code prefix", "open"),
    ("FACT-12", "FACT-12 the lantern feature flag defaults off in staging", "open"),
]
FILLER = (
    "routine discussion about refactoring the helper utilities and renaming "
    "internal variables for clarity across the affected modules turn {i}"
)


def test_money_jump_correctness(tmp_path: Path, clock: Callable[[], str]) -> None:
    session = JumpingRopeSession(
        tmp_path / "money",
        session_id="money-test",
        config=JumpConfig(
            rope_budget_tokens=650,
            jump_threshold_tokens=1_500,
            jump_every_n_turns=8,
        ),
        force_fallback=True,
        clock=clock,
    )
    session.record_event("state", "/srv/money", key="cwd")
    session.record_event("goal", "survive thirty turns with all facts", status="active")

    critical_schedule = dict(zip((1, 8, 15, 22), CRITICAL_FACTS, strict=True))
    demotable_schedule = dict(
        zip((3, 6, 9, 12, 16, 18, 21, 24), DEMOTABLE_FACTS, strict=True)
    )
    jumps = 0
    for turn in range(1, 31):
        if turn in critical_schedule:
            tag, text, priority = critical_schedule[turn]
            session.record_event("open", text, priority=priority)
        if turn in demotable_schedule:
            tag, text, section = demotable_schedule[turn]
            if section == "delta":
                session.record_event(section, text, path=f"src/{tag.lower()}.py")
            elif section == "open":
                session.record_event(section, text, priority=3)
            else:
                session.record_event(section, text, reason="planted")
        session.record_event("decision", FILLER.format(i=turn), reason="filler")
        session.note_turn(f"user turn {turn}: " + FILLER.format(i=turn))
        if session.should_jump():
            session.jump()
            jumps += 1

    reconstructed = session.jump()  # final jump: rope alone is the context
    jumps += 1
    assert jumps >= 3, f"only {jumps} jumps in 30 turns"
    assert count_tokens(reconstructed) <= 650

    # Reconstruction is from the rope ALONE and must parse as a valid rope.
    rope = RopeFile.parse(reconstructed)
    assert rope.session_id == "money-test"
    assert rope.jump_count == jumps

    # Every P0/P1 fact is present in the rope, verbatim-or-stubbed.
    for tag, _text, _priority in CRITICAL_FACTS:
        assert tag in reconstructed, f"critical {tag} lost from rope"

    # Every demoted fact comes back from TurboVec by key AND by search.
    records = session.store.dump()
    for tag, text, _section in DEMOTABLE_FACTS:
        matching = [
            r for r in records if tag in r.content and r.section != "KEYS"
        ]
        assert matching, f"{tag} never landed in TurboVec"
        record = matching[0]

        by_key = session.retrieve(record.key)  # exact key hit
        assert by_key.startswith(f"RETRIEVED|{record.key}|")
        assert tag in by_key

        top3 = session.store.search(text, k=3, session_id="money-test")
        assert any(tag in hit.content for hit in top3), f"{tag} not in top-3"

    session.close()


def test_jump_resets_cadence(tmp_path: Path, clock: Callable[[], str]) -> None:
    session = JumpingRopeSession(
        tmp_path / "cadence",
        session_id="cadence",
        config=JumpConfig(jump_every_n_turns=2, jump_threshold_tokens=99_999),
        force_fallback=True,
        clock=clock,
    )
    session.note_turn("one")
    assert not session.should_jump()
    session.note_turn("two")
    assert session.should_jump()
    text = session.jump()
    assert session.meta.turns_since_jump == 0
    assert session.meta.live_context_tokens == count_tokens(text)
    assert not session.should_jump()
    session.close()
