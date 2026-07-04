"""Seeded scenario generator: synthetic agentic sessions with owned ground truth.

A scenario is a stream of turns. Each turn carries events (facts, decisions,
goal transitions, filler churn) and may end with a probe — a question whose
answer the generator knows exactly. Probes are stratified by distance
(turns since the ground truth was introduced) so retention can be measured
as a curve, not a single number.

Everything is derived from one RNG seed: same seed → identical scenario.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

ADJECTIVES = [
    "amber", "brisk", "coral", "dusky", "ember", "frosted", "gilded", "hollow",
    "ionic", "jasper", "kelp", "lunar", "mossy", "nickel", "onyx", "pluvial",
]
NOUNS = [
    "anchor", "baffle", "crank", "dynamo", "eyelet", "flange", "gasket", "hinge",
    "impeller", "jig", "keel", "lattice", "manifold", "nozzle", "orifice", "pawl",
]
CHOICES = [
    "argon-cache", "basalt-queue", "cobalt-index", "delta-ledger", "ember-bus",
    "flint-store", "granite-lock", "helium-pool",
]
REASONS = [
    "latency", "durability", "auditability", "portability",
    "idempotency", "observability", "simplicity", "throughput",
]
FILLER_VERBS = ["renamed", "reordered", "tidied", "reindented", "annotated", "linted"]
FILLER_OBJS = ["helper utilities", "import blocks", "test fixtures", "log strings",
               "type hints", "shell scripts"]

SHORT, MEDIUM, LONG = "short", "medium", "long"
_DISTANCES = {SHORT: (2, 5), MEDIUM: (12, 25), LONG: (35, 60)}

# Conversational padding for the "chatty" scenario — real sessions wrap each
# fact in filler. The distinctive value survives verbatim; full-history pays
# for the padding, the rope's densify strips most of it (this is what makes
# unbound mode's economics real — the B5 gap in ROADMAP).
_CHATTER_PRE = [
    "Okay so I was just looking at this and honestly it seems like",
    "Right, quick heads up before we move on —",
    "Hmm, let me make sure I note this down properly:",
    "Good question. After digging through the code it turns out that",
    "So to summarize where we landed after all that back and forth,",
]
_CHATTER_POST = [
    "but let me know if you'd rather approach it differently.",
    "does that line up with what you were expecting on your end?",
    "anyway, moving on to the next thing on the list now.",
    "I'll keep that in mind as we continue with the rest of the work.",
    "figured it was worth flagging explicitly so we don't lose it later.",
]


def _chattify(text: str, rng: random.Random, padding: int) -> str:
    """Wrap ``text`` in ``padding`` sentences of conversational filler."""
    parts: list[str] = []
    for _ in range(padding):
        parts.append(rng.choice(_CHATTER_PRE))
    parts.append(text)
    for _ in range(padding):
        parts.append(rng.choice(_CHATTER_POST))
    return " ".join(parts)


@dataclass(frozen=True)
class Event:
    """One meaningful change, with both a transcript line and rope mapping."""

    kind: str  # fact | decision | goal | goal_done | filler
    text: str  # the line as it appears in a plain transcript
    rope_section: str  # delta | decision | open | goal | goal_done
    rope_kwargs: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Probe:
    turn: int
    kind: str  # fact | decision | status
    tag: str
    question: str
    expected_any: tuple[str, ...]  # answer must contain at least one
    ref_turn: int  # when the ground truth entered the session

    @property
    def distance(self) -> int:
        return self.turn - self.ref_turn

    @property
    def bucket(self) -> str:
        if self.distance <= 5:
            return SHORT
        if self.distance <= 25:
            return MEDIUM
        return LONG


@dataclass
class Scenario:
    seed: int
    n_turns: int
    turns: list[list[Event]]  # index 0 = turn 1
    probes: list[Probe]

    def probes_at(self, turn: int) -> list[Probe]:
        return [p for p in self.probes if p.turn == turn]


def generate(seed: int, n_turns: int = 80, chatty: int = 0) -> Scenario:
    rng = random.Random(seed)
    adjectives = rng.sample(ADJECTIVES, 14)
    nouns = rng.sample(NOUNS, 14)
    turns: list[list[Event]] = [[] for _ in range(n_turns)]
    probes: list[Probe] = []
    buckets = [SHORT, MEDIUM, LONG]

    def place_probe(kind: str, tag: str, ref_turn: int, question: str,
                    expected_any: tuple[str, ...], bucket: str) -> None:
        lo, hi = _DISTANCES[bucket]
        turn = min(ref_turn + rng.randint(lo, hi), n_turns)
        probes.append(Probe(turn=turn, kind=kind, tag=tag, question=question,
                            expected_any=expected_any, ref_turn=ref_turn))

    fact_step = max(2, (n_turns - 20) // 12)
    decision_step = max(3, (n_turns - 20) // 8)
    goal_step = max(3, (n_turns - 25) // 6)

    # -- facts: 12, evenly spread, probed round-robin across buckets ---------
    for i in range(12):
        adj, noun = adjectives[i], nouns[i]
        value = f"{CHOICES[i % 8].split('-')[0]}-{rng.randint(1000, 9999)}"
        ref_turn = min(2 + i * fact_step, n_turns - 1)
        text = f"the {adj} {noun} pipeline is pinned to build {value} until further notice"
        if chatty:
            text = _chattify(text, rng, chatty)
        section = "delta" if i % 2 == 0 else "open"
        kwargs: dict[str, object] = (
            {"path": f"svc/{noun}.py"} if section == "delta" else {"priority": 2}
        )
        turns[ref_turn - 1].append(
            Event(kind="fact", text=text, rope_section=section, rope_kwargs=kwargs)
        )
        place_probe(
            "fact", f"F{i + 1:02d}", ref_turn,
            f"What build is the {adj} {noun} pipeline pinned to?",
            (value,), buckets[i % 3],
        )

    # -- decisions: 8, with distinct choices and reasons ---------------------
    for i in range(8):
        noun = nouns[(i * 3 + 1) % 14]
        choice, reason = CHOICES[i], REASONS[i]
        ref_turn = min(4 + i * decision_step, n_turns - 1)
        text = (f"decided to adopt {choice} for the {noun} layer "
                f"because of {reason} constraints")
        if chatty:
            text = _chattify(text, rng, chatty)
        turns[ref_turn - 1].append(
            Event(kind="decision", text=text, rope_section="decision",
                  rope_kwargs={"reason": reason})
        )
        place_probe(
            "decision", f"D{i + 1:02d}", ref_turn,
            f"What did we adopt for the {noun} layer?",
            (choice,), buckets[i % 3],
        )

    # -- goals: 6 introduced, 3 later completed ------------------------------
    for i in range(6):
        noun = nouns[(i * 5 + 2) % 14]
        goal = f"ship the {noun} migration"
        ref_turn = min(3 + i * goal_step, n_turns - 2)
        turns[ref_turn - 1].append(
            Event(kind="goal", text=f"new goal (pending): {goal}",
                  rope_section="goal", rope_kwargs={"goal_num": i + 1})
        )
        done = i % 2 == 0
        status_ref = ref_turn
        if done:
            done_turn = min(ref_turn + rng.randint(6, 12), n_turns - 1)
            turns[done_turn - 1].append(
                Event(kind="goal_done",
                      text=f"goal status update: {goal} is now done",
                      rope_section="goal_done", rope_kwargs={"goal_num": i + 1})
            )
            status_ref = done_turn
        place_probe(
            "status", f"G{i + 1:02d}", status_ref,
            f"What is the status of the goal to {goal}?",
            ("done", "✓") if done else ("pending", "◌", "open", "not done"),
            buckets[i % 3],
        )

    # -- filler churn every turn ---------------------------------------------
    for t in range(n_turns):
        verb = FILLER_VERBS[t % len(FILLER_VERBS)]
        obj = FILLER_OBJS[(t * 5) % len(FILLER_OBJS)]
        turns[t].append(
            Event(kind="filler",
                  text=f"routine change {t + 1}: {verb} the {obj} across the module",
                  rope_section="decision", rope_kwargs={"reason": "routine"})
        )

    probes.sort(key=lambda p: p.turn)
    return Scenario(seed=seed, n_turns=n_turns, turns=turns, probes=probes)
