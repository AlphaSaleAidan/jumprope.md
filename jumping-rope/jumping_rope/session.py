"""JumpingRopeSession: the public API.

A session owns one rope file (tier 1) and one TurboVec store (tier 2) under a
data directory, and implements the jump cadence: jump when estimated live
context exceeds ``jump_threshold_tokens`` OR every ``jump_every_n_turns``
turns, whichever comes first.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .compactor import Compactor
from .notation import NotationProfile, get_profile
from .rope import RopeFile
from .tokens import count_tokens
from .turbovec import Embedder, TurboVec, format_retrieved

ROPE_FILENAME = "ROPE.md"
DB_FILENAME = "turbovec.db"
META_FILENAME = "session.json"

# Headroom the compactor needs above the fixed floor (legend + header +
# anchors) so never-demoted STATE/GOALS lines and KEYS stubs have room.
MIN_BUDGET_HEADROOM = 64


def minimum_budget_tokens(profile_name: str) -> int:
    """Smallest satisfiable rope budget for a notation profile."""
    legend = get_profile(profile_name).legend()
    floor = count_tokens(RopeFile.new("floor", "t", legend).render())
    return floor + MIN_BUDGET_HEADROOM


def _validate_budget(config: JumpConfig) -> None:
    min_budget = minimum_budget_tokens(config.notation_profile)
    if config.rope_budget_tokens < min_budget:
        raise ValueError(
            f"rope_budget_tokens={config.rope_budget_tokens} is below the "
            f"satisfiable minimum {min_budget} for profile "
            f"{config.notation_profile!r} (fixed floor = legend + header + "
            f"anchors, plus {MIN_BUDGET_HEADROOM} tokens headroom)"
        )


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class JumpConfig:
    rope_budget_tokens: int = 2_000
    jump_threshold_tokens: int = 12_000
    jump_every_n_turns: int = 8
    notation_profile: str = "symbolic-en"

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> JumpConfig:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})  # type: ignore[arg-type]


@dataclass
class SessionMeta:
    session_id: str
    turns_since_jump: int = 0
    live_context_tokens: int = 0
    config: JumpConfig = field(default_factory=JumpConfig)


class JumpingRopeSession:
    """Tier-1 rope + tier-2 TurboVec, with jump orchestration."""

    def __init__(
        self,
        data_dir: str | Path,
        session_id: str | None = None,
        config: JumpConfig | None = None,
        embedder: Embedder | None = None,
        force_fallback: bool = False,
        clock: Callable[[], str] = utc_now_iso,
    ) -> None:
        _validate_budget(config if config is not None else JumpConfig())
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        meta_path = self.data_dir / META_FILENAME
        rope_path = self.data_dir / ROPE_FILENAME
        if meta_path.exists() and rope_path.exists():
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            self.meta = SessionMeta(
                session_id=str(raw["session_id"]),
                turns_since_jump=int(raw["turns_since_jump"]),
                live_context_tokens=int(raw["live_context_tokens"]),
                config=JumpConfig.from_dict(raw.get("config", {})),
            )
            if config is not None:
                self.meta.config = config
            self.profile: NotationProfile = get_profile(self.meta.config.notation_profile)
            self.rope = RopeFile.parse(rope_path.read_text(encoding="utf-8"))
        else:
            sid = session_id if session_id is not None else uuid.uuid4().hex[:12]
            self.meta = SessionMeta(session_id=sid, config=config or JumpConfig())
            self.profile = get_profile(self.meta.config.notation_profile)
            self.rope = RopeFile.new(
                session_id=sid, timestamp=self._clock(), legend=self.profile.legend()
            )
        _validate_budget(self.meta.config)  # covers configs loaded from disk
        self.store = TurboVec(
            self.data_dir / DB_FILENAME,
            embedder=embedder,
            force_fallback=force_fallback,
        )
        self.compactor = Compactor(self.meta.config.rope_budget_tokens, self.store)
        self.save()

    # -- events -----------------------------------------------------------------

    def record_event(
        self,
        section: str,
        content: str,
        *,
        priority: int = 2,
        status: str = "pending",
        path: str | None = None,
        change_class: str = "mod",
        key: str | None = None,
        reason: str = "",
        densify: bool = True,
    ) -> None:
        """Append one meaningful change to the rope, keep it under budget.

        ``section`` is one of state | goal | decision | delta | open.
        """
        raw_tokens = count_tokens(content)
        text = self.profile.densify(content) if densify else content
        kind = section.lower()
        if kind == "state":
            if key is None:
                raise ValueError("state events require key=")
            self.rope.set_state(key, text)
        elif kind == "goal":
            self.rope.add_goal(text, status=status)
        elif kind == "decision":
            self.rope.add_decision(
                date=self._clock().split("T")[0],
                decision=text,
                reason=self.profile.densify(reason) if densify else reason,
            )
        elif kind == "delta":
            if path is None:
                raise ValueError("delta events require path=")
            self.rope.add_delta(path=path, change_class=change_class, summary=text)
        elif kind == "open":
            self.rope.add_open(text, priority=priority)
        else:
            raise ValueError(f"unknown event section {section!r}")
        self.rope.timestamp = self._clock()
        self.compactor.enforce(self.rope)
        self.meta.live_context_tokens += raw_tokens
        self.save()

    def set_goal_status(self, num: int, status: str) -> None:
        self.rope.set_goal_status(num, status)
        self.save()

    def archive(self, topic: str, content: str) -> str:
        """Store full-fidelity content directly in TurboVec (tier 2) and pin a
        retrieval key into ## KEYS. Used for material too bulky for the rope."""
        rec_key = self.store.put(
            session_id=self.meta.session_id,
            jump_index=self.rope.jump_count,
            section="ARCHIVE",
            content=content,
            created_at=self._clock(),
        )
        self.rope.add_key(topic=self.profile.densify(topic), turbovec_id=rec_key)
        self.compactor.enforce(self.rope)
        self.save()
        return rec_key

    def note_turn(self, *texts: str) -> None:
        """Account one conversational turn toward the jump cadence."""
        self.meta.turns_since_jump += 1
        self.meta.live_context_tokens += sum(count_tokens(t) for t in texts)
        self.save()

    # -- the jump ---------------------------------------------------------------

    def should_jump(self) -> bool:
        cfg = self.meta.config
        return (
            self.meta.live_context_tokens > cfg.jump_threshold_tokens
            or self.meta.turns_since_jump >= cfg.jump_every_n_turns
        )

    def jump(self) -> str:
        """Clear context: returns the rope text, the ONLY carried context."""
        text = self.compactor.jump(self.rope, self._clock())
        self.meta.turns_since_jump = 0
        self.meta.live_context_tokens = count_tokens(text)
        self.save()
        return text

    # -- retrieval ---------------------------------------------------------------

    def retrieve(self, query: str, k: int = 5) -> str:
        """Cache-miss lookup: exact key hit first, semantic search fallback.

        Returns compact ``RETRIEVED|key|content`` block(s) ready for context
        injection, or an empty string when nothing matches.
        """
        exact = self.store.get(query)
        if exact is not None:
            return format_retrieved(exact.key, exact.content)
        hits = self.store.search(query, k=k, session_id=self.meta.session_id)
        return "\n".join(format_retrieved(h.key, h.content) for h in hits)

    # -- persistence ---------------------------------------------------------------

    @property
    def rope_path(self) -> Path:
        return self.data_dir / ROPE_FILENAME

    def save(self) -> None:
        self.rope_path.write_text(self.rope.render(), encoding="utf-8")
        meta = {
            "session_id": self.meta.session_id,
            "turns_since_jump": self.meta.turns_since_jump,
            "live_context_tokens": self.meta.live_context_tokens,
            "config": asdict(self.meta.config),
        }
        (self.data_dir / META_FILENAME).write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

    def status(self) -> dict[str, object]:
        return {
            "session_id": self.meta.session_id,
            "jump_count": self.rope.jump_count,
            "rope_tokens": count_tokens(self.rope.render()),
            "rope_budget_tokens": self.meta.config.rope_budget_tokens,
            "live_context_tokens": self.meta.live_context_tokens,
            "turns_since_jump": self.meta.turns_since_jump,
            "should_jump": self.should_jump(),
            "store": self.store.stats(),
        }

    def close(self) -> None:
        self.store.close()
