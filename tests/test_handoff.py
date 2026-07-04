"""Handoff helpers shared by the pipe and proxy adapters."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.handoff import (
    apply_jump_policy,
    gist,
    history_tokens,
    last_user_message,
    message_text,
    record_turn,
)


def test_message_text_plain_and_content_parts() -> None:
    assert message_text({"role": "user", "content": "plain"}) == "plain"
    multimodal = {
        "role": "user",
        "content": [
            {"type": "text", "text": "part one"},
            {"type": "image_url", "image_url": {"url": "ignored"}},
            {"type": "text", "text": "part two"},
        ],
    }
    assert message_text(multimodal) == "part one\npart two"
    assert message_text({"role": "user"}) == ""


def test_history_tokens_and_last_user() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "an answer"},
        {"role": "user", "content": "second question"},
    ]
    assert history_tokens(messages) > 0
    last = last_user_message(messages)
    assert last is not None and last["content"] == "second question"
    assert last_user_message([{"role": "system", "content": "x"}]) is None


def test_gist_truncates() -> None:
    assert gist("one two three", words=8) == "one two three"
    long = " ".join(f"w{i}" for i in range(20))
    assert gist(long, words=8).endswith("…")


def test_record_turn_archives_last_user(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = JumpingRopeSession(
        tmp_path / "h", session_id="h", force_fallback=True, clock=clock
    )
    record_turn(session, [{"role": "user", "content": "the aardvark ledger is frozen"}])
    hits = session.store.search("aardvark ledger", k=1)
    assert hits and "aardvark" in hits[0].content
    session.close()


def test_apply_jump_policy_no_jump_passthrough(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = JumpingRopeSession(
        tmp_path / "p",
        session_id="p",
        config=JumpConfig(jump_every_n_turns=99, jump_threshold_tokens=99_999),
        force_fallback=True,
        clock=clock,
    )
    messages = [{"role": "user", "content": "hello"}]
    outbound, jumped = apply_jump_policy(session, messages)
    assert not jumped
    assert outbound == messages
    assert outbound is not messages  # defensive copy
    session.close()


def test_apply_jump_policy_token_threshold_triggers(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = JumpingRopeSession(
        tmp_path / "t",
        session_id="t",
        config=JumpConfig(jump_every_n_turns=99, jump_threshold_tokens=50),
        force_fallback=True,
        clock=clock,
    )
    messages = [
        {"role": "user", "content": "an extremely verbose message " * 30},
    ]
    outbound, jumped = apply_jump_policy(session, messages)
    assert jumped
    assert outbound[0]["role"] == "system"
    assert outbound[0]["content"].startswith("# ROPE v1")
    assert outbound[1]["role"] == "user"
    session.close()
