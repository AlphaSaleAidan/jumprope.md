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

import re
from collections.abc import Callable
from dataclasses import dataclass

from .rope import KeyItem, RopeFile
from .tokens import count_tokens
from .turbovec import TurboVec

_TOPIC_WORDS = 6

# -- keyring digests (adversarial finding A1a) --------------------------------
# A keyring stub must carry a lexical handle for every member it hides,
# or the member is unreachable to a literal cold reader. The digest is a
# comma-joined list of one significant token per transitive member,
# deduplicated, newest-first under a hard token budget with a "+n" overflow
# marker.
KEYRING_PREFIX = "KR:"
DIGEST_TOKEN_BUDGET = 48
_OVERFLOW_MARK = re.compile(r"\s*\+\d+$")
_DROP_TOKEN = re.compile(r"^(?:[DOGK]\d+|P[0-3]|KR|\d+|\d{4}-\d{2}-\d{2})$", re.IGNORECASE)
_DIGEST_STOP = frozenset(
    "the a an and or of to in on for with keyring demoted keys mod add del "
    "routine note number touching".split()
)
_WORD_SPLIT = re.compile(r"[^0-9A-Za-z_-]+")
_TAG_TOKEN = re.compile(r"^[A-Za-z]{1,4}-?\d{1,4}$")


def digest_tokens(topic: str) -> list[str]:
    """One significant token per member topic; keyrings flatten their own."""
    if topic.startswith(KEYRING_PREFIX):
        body = _OVERFLOW_MARK.sub("", topic[len(KEYRING_PREFIX):])
        return [t for t in body.split(",") if t]
    words = [
        w
        for w in _WORD_SPLIT.split(topic)
        if w and not _DROP_TOKEN.match(w) and w.lower() not in _DIGEST_STOP
    ]
    if not words:
        return []
    for word in words:  # prefer tag-like tokens (F07, CVE-123) — most distinctive
        if _TAG_TOKEN.match(word):
            return [word]
    return [words[0]]


def build_keyring_digest(
    members: list[KeyItem], token_budget: int = DIGEST_TOKEN_BUDGET
) -> str:
    """Digest topic for a keyring bundling ``members`` (oldest → newest)."""
    seen: set[str] = set()
    tokens: list[str] = []
    for member in members:
        for token in digest_tokens(member.topic):
            lowered = token.lower()
            if lowered not in seen:
                seen.add(lowered)
                tokens.append(token)
    kept: list[str] = []
    for token in reversed(tokens):  # newest members win the budget
        candidate = [token, *kept]
        if count_tokens(KEYRING_PREFIX + ",".join(candidate)) > token_budget:
            break
        kept = candidate
    dropped = len(tokens) - len(kept)
    digest = KEYRING_PREFIX + ",".join(kept)
    if dropped:
        digest += f" +{dropped}"
    return digest


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
    def __init__(
        self,
        budget_tokens: int | None,
        store: TurboVec,
        expand: Callable[[str], str] | None = None,
    ) -> None:
        self.budget_tokens = budget_tokens  # None = unbounded, never demote
        self.store = store
        # Keyring digests live on the never-demotable floor: scale their
        # budget to the rope budget so stubs cannot outgrow a small rope
        # (adversarial finding A17).
        self._digest_budget = (
            DIGEST_TOKEN_BUDGET
            if budget_tokens is None
            else min(DIGEST_TOKEN_BUDGET, max(16, budget_tokens // 8))
        )
        # Every retained stub costs ~25-40 tokens of never-demotable floor
        # (topic hint + key). Tight ropes keep none outside the keyring.
        self._keep_newest = 2 if budget_tokens is None or budget_tokens >= 500 else 0
        # Notation profiles with a session dictionary (ai-native) code the
        # rope; demoted content is EXPANDED before storage so semantic and
        # lexical retrieval still match natural-language queries.
        self._expand = expand if expand is not None else (lambda text: text)

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
            content=self._expand(content),
            created_at=rope.timestamp,
        )
        popped = self._pop_candidate(rope, section)
        assert popped == content, "peek/pop mismatch in demotion"
        topic = _topic_hint(content)
        rope.add_key(topic=topic, turbovec_id=key)
        return Demotion(section=section, topic=topic, key=key, content=content)

    def _coalesce_keys(self, rope: RopeFile, keep_newest: int | None = None) -> bool:
        """Bundle the oldest KEYS stubs into one TurboVec record.

        Returns False when there are too few stubs to make coalescing
        worthwhile (nothing would shrink).
        """
        keep = self._keep_newest if keep_newest is None else keep_newest
        if len(rope.keys) < max(keep + 2, 2):
            return False
        old = rope.keys[:-keep] if keep else list(rope.keys)
        content = self._expand("\n".join(k.render() for k in old))
        key = self.store.put(  # store BEFORE mutating the rope (A9)
            session_id=rope.session_id,
            jump_index=rope.jump_count,
            section="KEYS",
            content=content,
            created_at=rope.timestamp,
        )
        rope.keys = rope.keys[-keep:] if keep else []
        rope.add_key(
            topic=build_keyring_digest(old, self._digest_budget), turbovec_id=key
        )
        return True

    def enforce(self, rope: RopeFile) -> list[Demotion]:
        """Demote until the rendered rope fits the budget. Returns demotions.

        Unbounded mode (budget None): no demotion pressure — the rope is the
        persistent record and grows as needed; eviction happens on the
        transcript side instead (see handoff.apply_streaming_policy)."""
        if self.budget_tokens is None:
            return []
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
