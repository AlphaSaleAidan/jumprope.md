"""Context regimes: the policies under test.

Every regime consumes the same event stream and exposes (a) the context it
would hand the model at any moment and (b) an optional retrieval function.
The cost model is honest: an agent calls its model every turn, so each
regime accrues the token count of its current context once per turn.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.tokens import count_tokens

from .scenario import Event

RetrieveFn = Callable[[str], str]


class RegimeBase:
    name = "base"

    def __init__(self) -> None:
        self.turn_tokens: list[int] = []  # context cost accrued per turn

    def observe(self, turn: int, events: list[Event]) -> None:
        raise NotImplementedError

    def context(self) -> str:
        raise NotImplementedError

    def retriever(self) -> RetrieveFn | None:
        return None

    def end_turn(self) -> None:
        self.turn_tokens.append(count_tokens(self.context()))

    @property
    def total_tokens(self) -> int:
        return sum(self.turn_tokens)

    def close(self) -> None:
        pass


class FullHistoryRegime(RegimeBase):
    """The oracle ceiling: carry everything, pay for everything."""

    name = "full-history"

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def observe(self, turn: int, events: list[Event]) -> None:
        self.lines.extend(e.text for e in events)

    def context(self) -> str:
        return "\n".join(self.lines)


class TruncateRegime(RegimeBase):
    """Keep only the newest lines under a token budget (drop-oldest)."""

    name = "truncate"

    def __init__(self, budget_tokens: int = 800) -> None:
        super().__init__()
        self.budget = budget_tokens
        self.lines: list[str] = []

    def observe(self, turn: int, events: list[Event]) -> None:
        self.lines.extend(e.text for e in events)
        while self.lines and count_tokens("\n".join(self.lines)) > self.budget:
            self.lines.pop(0)

    def context(self) -> str:
        return "\n".join(self.lines)


class SummaryRegime(RegimeBase):
    """Generic auto-compaction stand-in: when over budget, the oldest half is
    'summarized' — each line collapses to its first four words. A second pass
    over the same line drops it entirely. Deterministic, and loses exactly
    the kind of detail real summarization loses (trailing specifics)."""

    name = "summary"

    def __init__(self, budget_tokens: int = 800) -> None:
        super().__init__()
        self.budget = budget_tokens
        self.lines: list[str] = []
        self.compressed: set[int] = set()  # indices already summarized once

    def _compact(self) -> None:
        while count_tokens("\n".join(self.lines)) > self.budget and self.lines:
            half = max(1, len(self.lines) // 2)
            changed = False
            for i in range(half):
                if i not in self.compressed:
                    words = self.lines[i].split()
                    if len(words) > 4:
                        self.lines[i] = " ".join(words[:4]) + "…"
                        changed = True
                    self.compressed.add(i)
            if not changed:  # second pass: drop the oldest summarized lines
                drop = max(1, half // 2)
                self.lines = self.lines[drop:]
                self.compressed = {i - drop for i in self.compressed if i >= drop}

    def observe(self, turn: int, events: list[Event]) -> None:
        self.lines.extend(e.text for e in events)
        self._compact()

    def context(self) -> str:
        return "\n".join(self.lines)


class RopeRegime(RegimeBase):
    """Jumping Rope: token-dense rope under a hard budget + TurboVec tier 2."""

    name = "rope"

    def __init__(
        self,
        rope_budget_tokens: int = 600,
        jump_every_n_turns: int = 8,
        data_dir: str | Path | None = None,
        config: JumpConfig | None = None,
    ) -> None:
        super().__init__()
        self._dir = Path(data_dir) if data_dir else Path(tempfile.mkdtemp(prefix="ropebench-"))
        self.session = JumpingRopeSession(
            self._dir,
            session_id="ropebench",
            config=config
            or JumpConfig(
                rope_budget_tokens=rope_budget_tokens,
                jump_threshold_tokens=rope_budget_tokens * 3,
                jump_every_n_turns=jump_every_n_turns,
            ),
            force_fallback=True,
            clock=lambda: "2026-07-03T00:00:00Z",
        )
        self._goal_nums: dict[object, int] = {}

    def observe(self, turn: int, events: list[Event]) -> None:
        for event in events:
            self._record(event)
        self.session.note_turn(" ".join(e.text for e in events))
        if self.session.should_jump():
            self.session.jump()

    def _record(self, event: Event) -> None:
        kw = event.rope_kwargs
        if event.rope_section == "delta":
            self.session.record_event(
                "delta", event.text, path=str(kw["path"])
            )
        elif event.rope_section == "open":
            self.session.record_event(
                "open", event.text, priority=int(str(kw["priority"]))
            )
        elif event.rope_section == "decision":
            self.session.record_event(
                "decision", event.text, reason=str(kw.get("reason", ""))
            )
        elif event.rope_section == "goal":
            self.session.record_event("goal", event.text, status="pending")
            self._goal_nums[kw["goal_num"]] = self.session.rope.goals[-1].num
        elif event.rope_section == "goal_done":
            rope_num = self._goal_nums.get(kw["goal_num"])
            if rope_num is not None:
                self.session.set_goal_status(rope_num, "done")

    def context(self) -> str:
        return self.session.rope.render()

    def retriever(self) -> RetrieveFn:
        return lambda query: self.session.retrieve(query, k=3)

    def close(self) -> None:
        self.session.close()


class RopeUnboundRegime(RopeRegime):
    """Jumping Rope in UNBOUND mode: the rope grows as needed (still dense),
    nothing demotes — decisions and facts stay on the rope verbatim. In a
    chat deployment the transcript is what gets evicted; in this event-driven
    bench the carried context is simply the rope itself."""

    name = "rope-unbound"

    def __init__(self, data_dir: str | Path | None = None) -> None:
        super().__init__(data_dir=data_dir, config=JumpConfig.unbound())

    def observe(self, turn: int, events: list[Event]) -> None:
        for event in events:
            self._record(event)
        self.session.note_turn(" ".join(e.text for e in events))
        # No jump: the rope is the persistent record.


class StreamingRopeRegime(RopeRegime):
    """Unbound rope with REAL streaming transcript eviction (closes B6).

    Instead of recording distilled events, this replays the scenario as a
    chat transcript and drives the *actual* ``apply_streaming_policy`` from
    jumping_rope — no reimplementation. Each turn the outbound payload is
    ``[system: rope] + uncovered transcript tail``; covered messages evict to
    the vault, so the payload stays flat instead of growing with history.
    Per-turn cost is that real outbound payload — the accounting the
    event-driven regimes could not do, and where unbound mode's economics
    actually live.
    """

    name = "rope-streaming"

    def __init__(self, data_dir: str | Path | None = None) -> None:
        super().__init__(data_dir=data_dir, config=JumpConfig.unbound())
        self._messages: list[dict[str, str]] = []
        self._last_outbound_tokens = 0

    def observe(self, turn: int, events: list[Event]) -> None:
        from jumping_rope.handoff import apply_streaming_policy

        text = " ".join(e.text for e in events)
        self._messages.append({"role": "user", "content": text})
        outbound, _evicted = apply_streaming_policy(self.session, self._messages)
        self._last_outbound_tokens = sum(
            count_tokens(str(m.get("content", ""))) for m in outbound
        )
        self._messages.append({"role": "assistant", "content": f"noted turn {turn}"})

    def end_turn(self) -> None:
        # Cost is the real outbound payload, not just the rope render.
        self.turn_tokens.append(self._last_outbound_tokens)


# Short aliases accepted on the CLI (--conditions), mapped to regime names.
CONDITION_ALIASES = {
    "carry": "full-history", "full": "full-history",
    "truncate": "truncate", "summarize": "summary", "summary": "summary",
    "rope": "rope", "unbound": "rope-unbound", "rope-unbound": "rope-unbound",
}


def default_regimes(
    budget_tokens: int = 800, only: list[str] | None = None
) -> list[RegimeBase]:
    all_regimes: list[RegimeBase] = [
        FullHistoryRegime(),
        TruncateRegime(budget_tokens=budget_tokens),
        SummaryRegime(budget_tokens=budget_tokens),
        RopeRegime(rope_budget_tokens=600),
        RopeUnboundRegime(),
    ]
    if only is None:
        return all_regimes
    wanted = {CONDITION_ALIASES.get(c, c) for c in only}
    return [r for r in all_regimes if r.name in wanted]
