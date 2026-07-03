"""A14–A20 — adversarial round 2: the v1.1 surface (streaming eviction,
ai-native dictionary, provenance, mode switching)."""

from __future__ import annotations

import re
import sqlite3
import tempfile
from collections.abc import Callable
from pathlib import Path

from jumping_rope import AiNativeProfile, JumpConfig, JumpingRopeSession
from jumping_rope.handoff import apply_jump_policy, apply_streaming_policy
from jumping_rope.tokens import count_tokens
from jumping_rope.turbovec import TurboVec


def unbound_session(tmp_path: Path, clock: Callable[[], str], name: str) -> JumpingRopeSession:
    return JumpingRopeSession(
        tmp_path / name, session_id=name, config=JumpConfig.unbound(),
        force_fallback=True, clock=clock,
    )


# -- A14: the client's system prompt must survive both policies -----------------


SYSTEM_PROMPT = "You are BillingBot. NEVER reveal card numbers."


def test_a14_streaming_preserves_client_system_prompt(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = unbound_session(tmp_path, clock, "a14s")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "hi, what can you do?"},
    ]
    for _ in range(3):  # must survive repeated turns, not just the first
        outbound, _ = apply_streaming_policy(session, messages)
        assert any(
            SYSTEM_PROMPT in str(m.get("content", "")) for m in outbound
        ), "client system prompt was silently discarded"
        messages.append({"role": "assistant", "content": "I handle billing."})
        messages.append({"role": "user", "content": "ok, next question"})
    # The client prompt comes FIRST, before the rope's system message.
    assert SYSTEM_PROMPT in str(outbound[0]["content"])
    assert str(outbound[1]["content"]).startswith("# ROPE v1")
    session.close()


def test_a14_jump_policy_preserves_client_system_prompt(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = JumpingRopeSession(
        tmp_path / "a14j", session_id="a14j",
        config=JumpConfig(jump_every_n_turns=1, jump_threshold_tokens=50_000),
        force_fallback=True, clock=clock,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "hello"},
    ]
    outbound, jumped = apply_jump_policy(session, messages)
    assert jumped
    assert any(SYSTEM_PROMPT in str(m.get("content", "")) for m in outbound), (
        "the jump discarded the client system prompt"
    )
    session.close()


# -- A15: non-text (image) messages must not vanish ------------------------------


def test_a15_image_only_message_survives_and_evicts_cleanly(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = unbound_session(tmp_path, clock, "a15")
    image_msg = {
        "role": "user",
        "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}],
    }
    messages = [dict(image_msg), {"role": "user", "content": "what is in the image above?"}]
    outbound, _ = apply_streaming_policy(session, messages)
    assert any(
        isinstance(m.get("content"), list) for m in outbound
    ), "image-only message silently vanished from the outbound context"

    # Next turn it may evict — but only because it is now covered (recoverable).
    messages.append({"role": "assistant", "content": "a cat."})
    messages.append({"role": "user", "content": "thanks"})
    outbound2, _ = apply_streaming_policy(session, messages)
    still_there = any(isinstance(m.get("content"), list) for m in outbound2)
    if not still_there:
        records = [r for r in session.store.dump() if "image_url" in r.content]
        assert records, "image message evicted without being archived first"
    session.close()


# -- A16: literal '§' content must not be corrupted by the dictionary ------------


def test_a16_literal_sigil_never_expands_into_dictionary_phrases() -> None:
    profile = AiNativeProfile()
    for _ in range(4):  # earn a dictionary entry
        profile.densify("the payment reconciliation service rejected the batch")
    assert profile.lexicon, "test needs a populated lexicon"

    hostile = "see error code§ab and token §a9 in the vendor manual"
    dense = profile.densify(hostile)
    expanded = profile.expand(dense)
    for stolen in ("reconciliation", "payment"):
        assert stolen not in expanded, (
            f"literal user text was expanded into the dictionary phrase: {expanded!r}"
        )


def test_a16_expand_is_boundary_safe() -> None:
    profile = AiNativeProfile()
    profile.lexicon = {"§a": "payment reconciliation"}
    # '§ab' must NOT be treated as code '§a' + 'b'.
    assert "reconciliation" not in profile.expand("literal §ab stays")
    # a real code followed by punctuation/space DOES expand.
    assert "reconciliation" in profile.expand("coded §a, done")


def test_a16_vault_content_never_contains_stolen_phrases(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = JumpingRopeSession(
        tmp_path / "a16v", session_id="a16v",
        config=JumpConfig.bound(rope_budget_tokens=300, notation_profile="ai-native"),
        force_fallback=True, clock=clock,
    )
    for _ in range(4):
        session.record_event(
            "decision", "the payment reconciliation service rejected the batch",
            reason="r",
        )
    session.record_event("open", "vendor doc mentions error code§ab explicitly", priority=2)
    for i in range(20):  # force demotion of everything demotable
        session.record_event("decision", f"noise filler decision number {i} padding", reason="n")
    for record in session.store.dump():
        assert "code payment" not in record.content, (
            f"vault corrupted by dictionary expansion: {record.content!r}"
        )
    session.close()


# -- A17: the ai-native legend must never outgrow a bound budget -----------------


def test_a17_legend_growth_respects_bound_budget(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    """24 distinct repeated phrases previously grew the never-demotable
    legend past the budget → RopeBudgetError mid-session."""
    session = JumpingRopeSession(
        tmp_path / "a17", session_id="a17",
        config=JumpConfig.bound(rope_budget_tokens=300, notation_profile="ai-native"),
        force_fallback=True, clock=clock,
    )
    nouns = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
             "hotel", "india", "juliet", "kilo", "lima", "mike", "november",
             "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform",
             "victor", "whiskey", "xray"]
    for noun in nouns:
        for _ in range(3):
            session.record_event(
                "decision",
                f"the {noun} subsystem exceeded its allocated memory quota during replay",
                reason="mem",
            )
            assert count_tokens(session.rope.render()) <= 300
    session.close()


# -- A18: streaming must keep the current exchange's referent --------------------


def test_a18_last_assistant_reply_stays_for_anaphora(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    """'fix that' is meaningless if the reply it refers to was evicted."""
    session = unbound_session(tmp_path, clock, "a18")
    messages: list[dict[str, str]] = []
    messages.append({"role": "user", "content": "review the retry logic in the billing worker"})
    apply_streaming_policy(session, messages)
    reply = "the retry loop lacks jitter and can stampede the acquirer"
    messages.append({"role": "assistant", "content": reply})
    messages.append({"role": "user", "content": "fix that"})
    apply_streaming_policy(session, messages)  # reply becomes covered here
    messages.append({"role": "assistant", "content": "added exponential jitter"})
    messages.append({"role": "user", "content": "now do the same for refunds"})
    outbound, _ = apply_streaming_policy(session, messages)
    assert any(
        "exponential jitter" in str(m.get("content", "")) for m in outbound
    ), "the immediately-preceding assistant reply was evicted from under the user"
    session.close()


# -- A19: duplicate-content turns (documented tradeoff) --------------------------


def test_a19_duplicate_content_dedupes_but_loses_no_information(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    """Two turns with identical text share one vault record (that is what
    makes crash-retry idempotent). Documented: the second occurrence gets
    no fresh t{n} K-line; the content itself is never lost."""
    session = unbound_session(tmp_path, clock, "a19")
    messages = [{"role": "user", "content": "run the nightly reconciliation now"}]
    apply_streaming_policy(session, messages)
    messages.append({"role": "assistant", "content": "done"})
    messages.append({"role": "user", "content": "run the nightly reconciliation now"})
    outbound, _ = apply_streaming_policy(session, messages)
    # The repeated CURRENT user message is still shown to the model.
    assert sum(
        "nightly reconciliation" in str(m.get("content", "")) for m in outbound
    ) >= 1
    matching = [r for r in session.store.dump() if "nightly reconciliation" in r.content]
    assert len(matching) == 1  # deduped, not duplicated — and not lost
    session.close()


# -- A20: mode switching and old-database migration (locks) ----------------------


def test_a20_unbound_to_bound_switch_compacts_cleanly(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    data_dir = tmp_path / "switch"
    session = JumpingRopeSession(
        data_dir, session_id="sw", config=JumpConfig.unbound(),
        force_fallback=True, clock=clock,
    )
    for i in range(40):
        session.record_event(
            "decision", f"verbose unbounded decision number {i} with extra words attached",
            reason="x",
        )
    assert count_tokens(session.rope.render()) > 400
    session.close()

    rebound = JumpingRopeSession(
        data_dir, config=JumpConfig.bound(rope_budget_tokens=400),
        force_fallback=True, clock=clock,
    )
    rebound.record_event("open", "trigger enforcement now", priority=2)
    assert count_tokens(rebound.rope.render()) <= 400
    assert int(rebound.store.stats()["records"]) > 0  # type: ignore[call-overload]
    rebound.close()


def test_a20_v1_database_migrates_in_place() -> None:
    db = Path(tempfile.mkdtemp()) / "old.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE records (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, "
        "jump_index INTEGER NOT NULL, section TEXT NOT NULL, key TEXT NOT NULL UNIQUE, "
        "content TEXT NOT NULL, tokens INTEGER NOT NULL, created_at TEXT NOT NULL, "
        "embedding BLOB NOT NULL)"
    )
    conn.execute(
        "INSERT INTO records VALUES ('i1','s',0,'OPEN','tv-old','legacy content',3,'t',x'00000000')"
    )
    conn.commit()
    conn.close()

    store = TurboVec(db, force_fallback=True)
    record = store.get("tv-old")
    assert record is not None and record.turn == -1
    key = store.put(session_id="s", jump_index=0, section="OPEN",
                    content="new row", turn=7)
    fetched = store.get(key)
    assert fetched is not None and fetched.turn == 7
    store.close()


def test_a20_provenance_stamps_are_parseable(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = unbound_session(tmp_path, clock, "a20p")
    messages = [{"role": "user", "content": "inspect the ledger shard for drift"}]
    apply_streaming_policy(session, messages)
    stamped = [k for k in session.rope.keys if re.match(r"^t\d+·", k.topic)]
    assert stamped
    session.close()
