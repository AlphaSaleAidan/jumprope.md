"""Chat-history handoff policy shared by the Open WebUI pipe and the proxy.

Given an OpenAI-style ``messages`` list, decide whether to jump. On a jump the
outgoing history is replaced by ``[system: rope contents] + [last user
message]`` and the naive history is left behind — its facts already live in
the rope (tier 1) or TurboVec (tier 2).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .session import JumpingRopeSession
from .tokens import count_tokens

Message = dict[str, Any]

_GIST_WORDS = 8


def message_text(message: Mapping[str, Any]) -> str:
    """Extract plain text from a chat message (string or content-parts)."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        parts: list[str] = []
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        return "\n".join(parts)
    return str(content)


def history_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    """Naive live-context estimate: token count of every message body."""
    return sum(count_tokens(message_text(m)) for m in messages)


def last_user_message(messages: Sequence[Mapping[str, Any]]) -> Message | None:
    for message in reversed(messages):
        if message.get("role") == "user":
            return dict(message)
    return None


def gist(text: str, words: int = _GIST_WORDS) -> str:
    head = " ".join(text.split()[:words])
    return head if len(text.split()) <= words else head + "…"


def record_turn(session: JumpingRopeSession, messages: Sequence[Mapping[str, Any]]) -> None:
    """Archive the newest user message full-fidelity into TurboVec."""
    last_user = last_user_message(messages)
    if last_user is not None:
        text = message_text(last_user)
        if text.strip():
            session.archive(topic=gist(text), content=text)


def apply_streaming_policy(
    session: JumpingRopeSession, messages: Sequence[Mapping[str, Any]]
) -> tuple[list[Message], bool]:
    """Unbound-rope mode: continuous transcript eviction, no episodic jump.

    Every transcript message whose content is already captured (archived
    full-fidelity in TurboVec, indexed by a t{turn}-stamped K-line) is
    auto-removed from the outgoing history. Outbound = [system: rope] +
    the uncovered tail (always including the current user message). The
    live context stays flat every turn instead of sawtoothing between
    jumps.

    Returns (outbound_messages, evicted_any).
    """
    session.meta.turns_since_jump += 1
    session.meta.total_turns += 1
    kept: list[Message] = []
    newly_seen: list[tuple[str, str]] = []
    last_user = last_user_message(messages)
    last_user_text = message_text(last_user) if last_user is not None else None
    evicted = False
    for message in messages:
        if message.get("role") == "system":
            continue  # the rope replaces system-carried state
        text = message_text(message)
        if not text.strip():
            continue
        is_current = (
            message.get("role") == "user" and text == last_user_text
        )
        if session.is_covered(text) and not is_current:
            evicted = True  # equivalent data already on the rope — drop it
            continue
        kept.append(dict(message))
        if not session.is_covered(text):
            newly_seen.append((str(message.get("role", "?")), text))
    for role, text in newly_seen:  # covered from the NEXT call onward
        session.archive(topic=f"{role}: {gist(text)}", content=text)
    outbound: list[Message] = [
        {"role": "system", "content": session.rope.render()},
        *kept,
    ]
    session.meta.live_context_tokens = history_tokens(outbound)
    session.save()
    return outbound, evicted


def apply_jump_policy(
    session: JumpingRopeSession, messages: Sequence[Mapping[str, Any]]
) -> tuple[list[Message], bool]:
    """Return (outbound_messages, jumped).

    Counts this call as one turn and uses the naive history size as the live
    context estimate. On breach of either configured limit, performs the jump:
    outbound history becomes the rope as a system message plus the last user
    message only.
    """
    session.meta.live_context_tokens = history_tokens(messages)
    session.meta.turns_since_jump += 1
    session.save()
    if not session.should_jump():
        return [dict(m) for m in messages], False
    rope_text = session.jump()
    outbound: list[Message] = [{"role": "system", "content": rope_text}]
    last_user = last_user_message(messages)
    if last_user is not None:
        outbound.append(last_user)
    return outbound, True
