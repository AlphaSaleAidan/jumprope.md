"""A1 — THE MONEY ATTACK: cold-session recovery through the keyring.

A fresh session sees only the rope. Can a literal-minded cold agent — a
deterministic policy, not an LLM — recover specific planted facts through
the two-hop keyring path using only what the rope shows it?

ColdAgent policy (worst realistic reader):
  (a) read ## KEYS lines
  (b) retrieve(key) only for stubs whose line lexically overlaps the question
      (case-folded, suffix-stripped)
  (c) on a keyring record, recurse into the member keys it lists — leaf
      members on overlap, nested keyrings unconditionally — max depth 3
  (d) fall back to ONE search(question, k=3) call
It never guesses opaque IDs.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.rope import RopeFile

# 20 planted facts with distinct topics.
FACTS = {
    f"F{i:02d}": text
    for i, text in enumerate(
        [
            "the walrus schema stores tungsten keys in namespace omega",
            "the heron cache evicts quartz entries after nine minutes",
            "the falcon queue drains into the basalt warehouse nightly",
            "the juniper endpoint requires a cobalt bearer token",
            "marble reports aggregate by fortnight not by month",
            "the osprey worker retries exactly seven times with jitter",
            "garnet tenants shard by postal code prefix",
            "the lantern feature flag defaults off in staging",
            "the pelican webhook signs payloads with rotating hmac",
            "onyx migrations run only during the maintenance window",
            "the sparrow scheduler skips leap seconds entirely",
            "topaz invoices round half-even to two decimals",
            "the badger daemon binds only to the loopback interface",
            "cedar backups replicate to three availability zones",
            "the mantis parser rejects mixed indentation outright",
            "silver sessions expire after eleven idle minutes",
            "the puffin cluster autoscales on queue depth not cpu",
            "umber logs redact account numbers at ingestion",
            "the viper gateway rate limits by api key not ip",
            "willow caches invalidate through the event bus only",
        ],
        start=1,
    )
}
_SUFFIXES = ("ing", "edly", "ed", "es", "ly", "s")
_STOPWORDS = {
    "the", "and", "not", "for", "with", "into", "only", "after", "every",
    "exact", "exactly", "through", "during", "off", "out", "all", "are",
    "keyring", "demoted", "key", "keys",
}


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> set[str]:
    return {
        _stem(w)
        for w in re.split(r"[^0-9a-z]+", text.casefold())
        if len(w) >= 3 and w not in _STOPWORDS and _stem(w) not in _STOPWORDS
    }


_K_LINE = re.compile(r"^K(\d+)\|(?P<topic>[^|]*)\|(?P<key>.+)$")


class ColdAgent:
    """Deterministic literal-minded reader of a rope it has never seen."""

    def __init__(self, session: JumpingRopeSession, rope_text: str) -> None:
        self.session = session
        self.rope = RopeFile.parse(rope_text)
        self.rope_text = rope_text

    def _overlaps(self, line: str, question_tokens: set[str]) -> bool:
        return bool(_tokens(line) & question_tokens)

    def _is_keyring(self, topic: str) -> bool:
        return topic.startswith("KR:") or topic.startswith("keyring")

    def answer(self, question: str) -> tuple[str, str] | None:
        """Return (path, evidence) or None.

        Paths: rope (verbatim in carried context) | direct | keyring | search.
        """
        qtok = _tokens(question)

        # (0): the carried rope itself — a cold reader has it in context.
        # Best-matching line wins, and only on ≥2 shared content words: a
        # single generic-token overlap (e.g. "queue" or the LEGEND's
        # "migration") is not an answer even for a literal reader.
        best_line, best_overlap = "", 0
        for line in self.rope_text.splitlines():
            if line.startswith(("## ", "# ", "K")):
                continue
            overlap = len(_tokens(line) & qtok)
            if overlap > best_overlap:
                best_overlap, best_line = overlap, line
        if best_overlap >= 2:
            return ("rope", best_line)

        # (a)/(b): direct stubs first.
        for stub in self.rope.keys:
            if self._is_keyring(stub.topic):
                continue
            if self._overlaps(f"{stub.topic}", qtok):
                record = self.session.store.get(stub.turbovec_id)
                if record is not None and self._overlaps(record.content, qtok):
                    return ("direct", record.content)

        # (c): keyring stubs whose line overlaps; recurse into members.
        for stub in self.rope.keys:
            if not self._is_keyring(stub.topic):
                continue
            if self._overlaps(stub.topic, qtok):
                evidence = self._descend(stub.turbovec_id, qtok, depth=1)
                if evidence is not None:
                    return ("keyring", evidence)

        # (d): one semantic fallback.
        hits = self.session.store.search(
            question, k=3, session_id=self.session.meta.session_id
        )
        for hit in hits:
            if self._overlaps(hit.content, qtok):
                return ("search", hit.content)
        return None

    def _descend(self, key: str, qtok: set[str], depth: int) -> str | None:
        if depth > 3:
            return None
        record = self.session.store.get(key)
        if record is None:
            return None
        if record.section != "KEYS":
            return record.content if self._overlaps(record.content, qtok) else None
        for line in record.content.splitlines():
            match = _K_LINE.match(line)
            if match is None:
                continue
            topic, member_key = match.group("topic"), match.group("key")
            if self._is_keyring(topic):  # nested keyrings: always recurse
                found = self._descend(member_key, qtok, depth + 1)
                if found is not None:
                    return found
            elif self._overlaps(topic, qtok):
                found = self._descend(member_key, qtok, depth + 1)
                if found is not None:
                    return found
        return None


def keyring_generation_depth(session: JumpingRopeSession) -> int:
    """Longest keyring→keyring chain in the store."""
    keyrings = {
        r.key: r.content for r in session.store.dump() if r.section == "KEYS"
    }

    def depth_of(key: str, seen: frozenset[str]) -> int:
        if key not in keyrings or key in seen:
            return 0
        best = 0
        for line in keyrings[key].splitlines():
            match = _K_LINE.match(line)
            if match:
                best = max(best, depth_of(match.group("key"), seen | {key}))
        return 1 + best

    return max((depth_of(k, frozenset()) for k in keyrings), default=0)


def run_hostile_session(
    tmp_path: Path, clock: Callable[[], str]
) -> JumpingRopeSession:
    """60 turns, 20 facts, budget 600 — hostile compaction."""
    session = JumpingRopeSession(
        tmp_path / "cold",
        session_id="cold",
        config=JumpConfig(
            rope_budget_tokens=600,
            jump_threshold_tokens=2_000,
            jump_every_n_turns=10,
        ),
        force_fallback=True,
        clock=clock,
    )
    session.record_event("state", "/srv/cold", key="cwd")
    session.record_event("goal", "survive hostile compaction", status="active")
    fact_items = list(FACTS.items())
    for turn in range(1, 61):
        if turn % 3 == 0 and turn // 3 <= 20:
            tag, text = fact_items[turn // 3 - 1]
            session.record_event("open", f"{tag} {text}", priority=3, densify=False)
        session.record_event(
            "decision",
            f"routine refactor note number {turn} touching internal helper naming",
            reason="routine",
            densify=False,
        )
        session.note_turn(f"turn {turn}")
        if session.should_jump():
            session.jump()
    session.jump()
    return session


def test_a1_cold_agent_recovers_facts_through_keyring(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = run_hostile_session(tmp_path, clock)

    # The compaction regime really was hostile: keyrings of keyrings formed.
    depth = keyring_generation_depth(session)
    print(f"\n[a1] keyring generation depth: {depth}")
    assert depth >= 2, "scenario failed to produce nested keyrings"

    carried = session.rope.render()
    agent = ColdAgent(session, carried)

    paths: dict[str, str] = {}
    for tag, text in FACTS.items():
        result = agent.answer(f"{tag} {text}")
        if result is not None:
            path, evidence = result
            if tag in evidence:  # wrong evidence = not recovered
                paths[tag] = path

    recovered = len(paths)
    by_path = {p: sorted(t for t, q in paths.items() if q == p)
               for p in ("rope", "direct", "keyring", "search")}
    print(f"[a1] recovered {recovered}/20; paths: "
          + ", ".join(f"{p}={len(v)}" for p, v in by_path.items()))
    for p, v in by_path.items():
        print(f"[a1]   {p}: {v}")

    assert recovered >= 19, f"cold agent recovered only {recovered}/20 facts"
    # The keyring hop must be load-bearing, not dead code masked by search.
    assert len(by_path["keyring"]) >= 5, (
        f"only {len(by_path['keyring'])} facts came back via the keyring hop"
    )
    session.close()


def test_a1a_keyring_stubs_carry_member_topic_digest(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    """Every keyring stub must digest ALL member topics within its line
    budget. A member whose topic contributes nothing to the digest is
    unreachable to a literal reader (finding A1a)."""
    session = run_hostile_session(tmp_path, clock)
    keyring_records = {
        r.key: r.content for r in session.store.dump() if r.section == "KEYS"
    }
    stubs: list[tuple[str, str]] = []  # (digest topic, record key)
    for stub in session.rope.keys:
        if stub.turbovec_id in keyring_records:
            stubs.append((stub.topic, stub.turbovec_id))
    for content in keyring_records.values():  # nested stubs too
        for line in content.splitlines():
            match = _K_LINE.match(line)
            if match and match.group("key") in keyring_records:
                stubs.append((match.group("topic"), match.group("key")))

    assert stubs, "no keyring stubs found — scenario not hostile enough"
    uncovered_total = 0
    member_total = 0
    for topic, key in stubs:
        digest_tokens = _tokens(topic)
        for line in keyring_records[key].splitlines():
            match = _K_LINE.match(line)
            if match is None:
                continue
            member_total += 1
            member_topic_tokens = _tokens(match.group("topic"))
            if not (member_topic_tokens & digest_tokens):
                uncovered_total += 1
    coverage = 1 - uncovered_total / member_total if member_total else 0.0
    print(f"\n[a1a] digest coverage: {member_total - uncovered_total}/{member_total} "
          f"members ({coverage:.0%})")
    assert uncovered_total == 0, (
        f"{uncovered_total}/{member_total} keyring members have no digest "
        "representation — unreachable to a literal reader"
    )
    session.close()
