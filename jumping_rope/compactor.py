"""Compactor: rope budget enforcement, demotion policy, jump orchestration.

Policy (deterministic):
- LEGEND, STATE and GOALS are never demoted.
- Demotion candidates are drained oldest-first, section by section, in the
  order DECISIONS -> DELTA -> OPEN. Within OPEN, only P2/P3 items are
  demotable and lower-priority (P3) items go first.
- A demoted line is removed from its section and replaced by a one-line stub
  in ## KEYS carrying a topic hint and the TurboVec retrieval key.
- When everything demotable is drained and the rope is still over budget,
  the oldest KEYS stubs are coalesced into a single "keyring" bundle stored
  in TurboVec (retrieval becomes two-hop but nothing is ever lost).
"""

from __future__ import annotations

from dataclasses import dataclass

from .rope import RopeFile
from .tokens import count_tokens
from .turbovec import TurboVec

_TOPIC_WORDS = 6


class RopeBudgetError(RuntimeError):
    """Raised when a rope cannot be compacted under its budget."""


@dataclass
class Demotion:
    section: str
    topic: str
    key: str
    content: str


def _topic_hint(text: str) -> str:
    words = text.split()
    hint = " ".join(words[:_TOPIC_WORDS])
    return hint if len(words) <= _TOPIC_WORDS else hint + "…"


class Compactor:
    def __init__(self, budget_tokens: int, store: TurboVec) -> None:
        self.budget_tokens = budget_tokens
        self.store = store

    # -- demotion -------------------------------------------------------------

    def _next_candidate(self, rope: RopeFile) -> tuple[str, str] | None:
        """Return (section, rendered-content) of the oldest demotable item."""
        if rope.decisions:
            return "DECISIONS", rope.decisions[0].render()
        if rope.delta:
            return "DELTA", rope.delta[0].render()
        for priority in (3, 2):
            for item in rope.open_items:
                if item.priority == priority:
                    return "OPEN", item.render()
        return None

    def _pop_candidate(self, rope: RopeFile, section: str) -> str:
        if section == "DECISIONS":
            return rope.decisions.pop(0).render()
        if section == "DELTA":
            return rope.delta.pop(0).render()
        for priority in (3, 2):
            for i, item in enumerate(rope.open_items):
                if item.priority == priority:
                    return rope.open_items.pop(i).render()
        raise RopeBudgetError("no demotable item in OPEN")

    def demote_one(self, rope: RopeFile) -> Demotion | None:
        """Demote the single oldest/lowest-priority item to TurboVec.

        The store write happens BEFORE any rope mutation: if it raises
        (disk full, I/O error) the rope is untouched and nothing is lost
        (adversarial finding A9). Content-addressed keys make the retried
        write idempotent.
        """
        candidate = self._next_candidate(rope)
        if candidate is None:
            return None
        section, content = candidate
        key = self.store.put(
            session_id=rope.session_id,
            jump_index=rope.jump_count,
            section=section,
            content=content,
            created_at=rope.timestamp,
        )
        popped = self._pop_candidate(rope, section)
        assert popped == content, "peek/pop mismatch in demotion"
        topic = _topic_hint(content)
        rope.add_key(topic=topic, turbovec_id=key)
        return Demotion(section=section, topic=topic, key=key, content=content)

    def _coalesce_keys(self, rope: RopeFile, keep_newest: int = 2) -> bool:
        """Bundle the oldest KEYS stubs into one TurboVec record.

        Returns False when there are too few stubs to make coalescing
        worthwhile (< keep_newest + 2).
        """
        if len(rope.keys) < keep_newest + 2:
            return False
        old = rope.keys[:-keep_newest]
        content = "\n".join(k.render() for k in old)
        key = self.store.put(  # store BEFORE mutating the rope (A9)
            session_id=rope.session_id,
            jump_index=rope.jump_count,
            section="KEYS",
            content=content,
            created_at=rope.timestamp,
        )
        rope.keys = rope.keys[-keep_newest:]
        rope.add_key(topic=f"keyring:{len(old)} demoted keys", turbovec_id=key)
        return True

    def enforce(self, rope: RopeFile) -> list[Demotion]:
        """Demote until the rendered rope fits the budget. Returns demotions."""
        demotions: list[Demotion] = []
        while count_tokens(rope.render()) > self.budget_tokens:
            demotion = self.demote_one(rope)
            if demotion is None:
                if self._coalesce_keys(rope):
                    continue
                raise RopeBudgetError(
                    "rope exceeds budget and nothing is demotable: never-demoted "
                    "sections (LEGEND/STATE/GOALS) alone exceed "
                    f"{self.budget_tokens} tokens "
                    f"(current: {count_tokens(rope.render())})"
                )
            demotions.append(demotion)
        return demotions

    # -- the jump ---------------------------------------------------------------

    def jump(self, rope: RopeFile, timestamp: str) -> str:
        """Perform a jump: enforce budget, bump jump count, return the rope
        text — the ONLY context handed to the fresh session."""
        self.enforce(rope)
        rope.jump_count += 1
        rope.timestamp = timestamp
        rope.validate()
        return rope.render()
