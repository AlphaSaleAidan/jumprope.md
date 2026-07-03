"""RopeFile: parse, render, append and validate the ROPE.md v1 spec.

Layout (fixed section order, stable anchors, no blank-line padding):

    # ROPE v1 | sess:{session_id} | j:{jump_count} | t:{utc_iso}
    ## LEGEND
    ## STATE      key:value lines
    ## GOALS      {glyph} G{n}|{text}
    ## DECISIONS  D{n}|{date}|{decision}|{reason}
    ## DELTA      {path}|{change_class}|{summary}
    ## OPEN       O{n}|P{p}|{text}
    ## KEYS       K{n}|{topic}|{turbovec_id}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .notation import STATUS_GLYPHS

ROPE_VERSION = "ROPE v1"
SECTIONS = ("LEGEND", "STATE", "GOALS", "DECISIONS", "DELTA", "OPEN", "KEYS")
NEVER_DEMOTED = ("LEGEND", "STATE", "GOALS")
_VALID_GLYPHS = frozenset(STATUS_GLYPHS.values())

_HEADER_RE = re.compile(
    r"^# ROPE v1 \| sess:(?P<sid>\S+) \| j:(?P<jc>\d+) \| t:(?P<ts>\S+)$"
)
_GOAL_RE = re.compile(r"^(?P<glyph>\S+) G(?P<num>\d+)\|(?P<text>.*)$")
_DECISION_RE = re.compile(
    r"^D(?P<num>\d+)\|(?P<date>[^|]*)\|(?P<decision>[^|]*)\|(?P<reason>.*)$"
)
_DELTA_RE = re.compile(r"^(?P<path>[^|]+)\|(?P<cls>[^|]+)\|(?P<summary>.*)$")
_OPEN_RE = re.compile(r"^O(?P<num>\d+)\|P(?P<prio>[0-3])\|(?P<text>.*)$")
_KEY_RE = re.compile(r"^K(?P<num>\d+)\|(?P<topic>[^|]*)\|(?P<tvid>.*)$")


class RopeParseError(ValueError):
    """Raised when text does not conform to the ROPE v1 spec."""


class RopeValidationError(ValueError):
    """Raised when a rope's structure violates the spec."""


# Every code point Python's str.splitlines() treats as a line boundary.
# Neutralizing only "\n" leaves the rope injectable via \r, \x0b, \x85,
# U+2028 etc. (adversarial finding A7).
_LINE_BREAKS = re.compile(r"[\r\n\v\f\x1c\x1d\x1e\x85  ]+")
_LEADING_HASHES = re.compile(r"^#+")
_SESSION_ID_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_field(text: str) -> str:
    """Make free text safe for one-line pipe-delimited records."""
    return _LINE_BREAKS.sub("; ", text).replace("|", "/").strip()


def sanitize_line_leading(text: str, fallback: str) -> str:
    """Sanitize a field rendered at the START of a line (DELTA path,
    STATE key). A leading '#' run would otherwise be parsed as a rope
    anchor or header (adversarial finding A6); it is replaced with the
    visually equivalent fullwidth '＃'. Empty fields get ``fallback``."""
    out = sanitize_field(text)
    match = _LEADING_HASHES.match(out)
    if match:
        out = "＃" * len(match.group()) + out[match.end():]
    return out or fallback


def sanitize_session_id(session_id: str) -> str:
    """Header-safe session id (the header is `| `-delimited free text)."""
    out = _SESSION_ID_SAFE.sub("-", session_id).strip("-")
    return out or "session"


@dataclass
class GoalItem:
    num: int
    status: str  # glyph
    text: str

    def render(self) -> str:
        return f"{self.status} G{self.num}|{self.text}"


@dataclass
class DecisionItem:
    num: int
    date: str
    decision: str
    reason: str

    def render(self) -> str:
        return f"D{self.num}|{self.date}|{self.decision}|{self.reason}"


@dataclass
class DeltaItem:
    path: str
    change_class: str
    summary: str

    def render(self) -> str:
        return f"{self.path}|{self.change_class}|{self.summary}"


@dataclass
class OpenItem:
    num: int
    priority: int  # 0 (highest) .. 3
    text: str

    def render(self) -> str:
        return f"O{self.num}|P{self.priority}|{self.text}"


@dataclass
class KeyItem:
    num: int
    topic: str
    turbovec_id: str

    def render(self) -> str:
        return f"K{self.num}|{self.topic}|{self.turbovec_id}"


@dataclass
class RopeFile:
    session_id: str
    jump_count: int
    timestamp: str  # UTC ISO-8601
    legend: str = ""
    state: dict[str, str] = field(default_factory=dict)
    goals: list[GoalItem] = field(default_factory=list)
    decisions: list[DecisionItem] = field(default_factory=list)
    delta: list[DeltaItem] = field(default_factory=list)
    open_items: list[OpenItem] = field(default_factory=list)
    keys: list[KeyItem] = field(default_factory=list)

    # -- construction -----------------------------------------------------

    @classmethod
    def new(cls, session_id: str, timestamp: str, legend: str) -> RopeFile:
        return cls(
            session_id=sanitize_session_id(session_id),
            jump_count=0,
            timestamp=timestamp,
            legend=legend,
        )

    # -- append API --------------------------------------------------------

    def set_state(self, key: str, value: str) -> None:
        safe_key = sanitize_line_leading(key.replace(":", "="), fallback="note")
        self.state[safe_key] = sanitize_field(value)

    def add_goal(self, text: str, status: str = "pending") -> GoalItem:
        glyph = STATUS_GLYPHS.get(status, status)
        if glyph not in _VALID_GLYPHS:
            raise RopeValidationError(f"unknown goal status {status!r}")
        num = max((g.num for g in self.goals), default=0) + 1
        item = GoalItem(num=num, status=glyph, text=sanitize_field(text))
        self.goals.append(item)
        return item

    def set_goal_status(self, num: int, status: str) -> None:
        glyph = STATUS_GLYPHS.get(status, status)
        if glyph not in _VALID_GLYPHS:
            raise RopeValidationError(f"unknown goal status {status!r}")
        for goal in self.goals:
            if goal.num == num:
                goal.status = glyph
                return
        raise RopeValidationError(f"no goal G{num}")

    def add_decision(self, date: str, decision: str, reason: str) -> DecisionItem:
        num = max((d.num for d in self.decisions), default=0) + 1
        item = DecisionItem(
            num=num,
            date=sanitize_field(date),
            decision=sanitize_field(decision),
            reason=sanitize_field(reason),
        )
        self.decisions.append(item)
        return item

    def add_delta(self, path: str, change_class: str, summary: str) -> DeltaItem:
        path_s = sanitize_line_leading(path, fallback="unknown")
        item = DeltaItem(
            path=path_s,
            change_class=sanitize_field(change_class) or "mod",
            summary=sanitize_field(summary),
        )
        for i, existing in enumerate(self.delta):
            if existing.path == path_s:  # change map: newest entry wins
                self.delta[i] = item
                return item
        self.delta.append(item)
        return item

    def add_open(self, text: str, priority: int) -> OpenItem:
        if priority not in (0, 1, 2, 3):
            raise RopeValidationError(f"priority must be 0..3, got {priority}")
        num = max((o.num for o in self.open_items), default=0) + 1
        item = OpenItem(num=num, priority=priority, text=sanitize_field(text))
        self.open_items.append(item)
        return item

    def add_key(self, topic: str, turbovec_id: str) -> KeyItem:
        num = max((k.num for k in self.keys), default=0) + 1
        item = KeyItem(
            num=num,
            topic=sanitize_field(topic),
            turbovec_id=sanitize_field(turbovec_id),
        )
        self.keys.append(item)
        return item

    # -- render / parse ----------------------------------------------------

    def render(self) -> str:
        lines: list[str] = [
            f"# {ROPE_VERSION} | sess:{self.session_id} | "
            f"j:{self.jump_count} | t:{self.timestamp}"
        ]
        lines.append("## LEGEND")
        if self.legend:
            lines.extend(self.legend.splitlines())
        lines.append("## STATE")
        lines.extend(f"{k}:{v}" for k, v in self.state.items())
        lines.append("## GOALS")
        lines.extend(g.render() for g in self.goals)
        lines.append("## DECISIONS")
        lines.extend(d.render() for d in self.decisions)
        lines.append("## DELTA")
        lines.extend(d.render() for d in self.delta)
        lines.append("## OPEN")
        lines.extend(o.render() for o in self.open_items)
        lines.append("## KEYS")
        lines.extend(k.render() for k in self.keys)
        return "\n".join(lines) + "\n"

    @classmethod
    def parse(cls, text: str) -> RopeFile:
        lines = text.splitlines()
        if not lines:
            raise RopeParseError("empty rope text")
        header = _HEADER_RE.match(lines[0])
        if header is None:
            raise RopeParseError(f"bad header line: {lines[0]!r}")
        rope = cls(
            session_id=header.group("sid"),
            jump_count=int(header.group("jc")),
            timestamp=header.group("ts"),
        )
        section: str | None = None
        legend_lines: list[str] = []
        seen: list[str] = []
        for raw in lines[1:]:
            if raw.startswith("## "):
                section = raw[3:].strip()
                if section not in SECTIONS:
                    raise RopeParseError(f"unknown section {section!r}")
                seen.append(section)
                continue
            if section is None:
                raise RopeParseError(f"content before first section: {raw!r}")
            if not raw.strip():
                raise RopeParseError("blank-line padding is not allowed")
            cls._parse_line(rope, section, raw, legend_lines)
        if tuple(seen) != SECTIONS:
            raise RopeParseError(
                f"sections must be exactly {SECTIONS} in order, got {tuple(seen)}"
            )
        rope.legend = "\n".join(legend_lines)
        return rope

    @staticmethod
    def _parse_line(
        rope: RopeFile, section: str, raw: str, legend_lines: list[str]
    ) -> None:
        if section == "LEGEND":
            legend_lines.append(raw)
            return
        if section == "STATE":
            key, sep, value = raw.partition(":")
            if not sep:
                raise RopeParseError(f"bad STATE line: {raw!r}")
            rope.state[key] = value
            return
        if section == "GOALS":
            m = _GOAL_RE.match(raw)
            if m is None or m.group("glyph") not in _VALID_GLYPHS:
                raise RopeParseError(f"bad GOALS line: {raw!r}")
            rope.goals.append(
                GoalItem(
                    num=int(m.group("num")),
                    status=m.group("glyph"),
                    text=m.group("text"),
                )
            )
            return
        if section == "DECISIONS":
            m = _DECISION_RE.match(raw)
            if m is None:
                raise RopeParseError(f"bad DECISIONS line: {raw!r}")
            rope.decisions.append(
                DecisionItem(
                    num=int(m.group("num")),
                    date=m.group("date"),
                    decision=m.group("decision"),
                    reason=m.group("reason"),
                )
            )
            return
        if section == "DELTA":
            m = _DELTA_RE.match(raw)
            if m is None:
                raise RopeParseError(f"bad DELTA line: {raw!r}")
            rope.delta.append(
                DeltaItem(
                    path=m.group("path"),
                    change_class=m.group("cls"),
                    summary=m.group("summary"),
                )
            )
            return
        if section == "OPEN":
            m = _OPEN_RE.match(raw)
            if m is None:
                raise RopeParseError(f"bad OPEN line: {raw!r}")
            rope.open_items.append(
                OpenItem(
                    num=int(m.group("num")),
                    priority=int(m.group("prio")),
                    text=m.group("text"),
                )
            )
            return
        m = _KEY_RE.match(raw)
        if m is None:
            raise RopeParseError(f"bad KEYS line: {raw!r}")
        rope.keys.append(
            KeyItem(
                num=int(m.group("num")),
                topic=m.group("topic"),
                turbovec_id=m.group("tvid"),
            )
        )

    # -- validation ----------------------------------------------------------

    def validate(self) -> None:
        """Raise RopeValidationError on any spec violation."""
        if not self.session_id or any(c.isspace() for c in self.session_id):
            raise RopeValidationError("session_id must be non-empty, no whitespace")
        if self.jump_count < 0:
            raise RopeValidationError("jump_count must be >= 0")
        for goal in self.goals:
            if goal.status not in _VALID_GLYPHS:
                raise RopeValidationError(f"goal G{goal.num} has bad glyph")
        for seq_name, nums in (
            ("goals", [g.num for g in self.goals]),
            ("decisions", [d.num for d in self.decisions]),
            ("open", [o.num for o in self.open_items]),
            ("keys", [k.num for k in self.keys]),
        ):
            if nums != sorted(nums):
                raise RopeValidationError(f"{seq_name} numbering must be increasing")
        for item in self.open_items:
            if item.priority not in (0, 1, 2, 3):
                raise RopeValidationError(f"O{item.num} priority out of range")
        rendered = self.render()
        if "\n\n" in rendered:
            raise RopeValidationError("blank-line padding in render")
        RopeFile.parse(rendered)  # must round-trip
