"""Notation profiles: pluggable token-density transforms for rope content.

A profile turns plain prose into the dense, low-redundancy notation the rope
is written in. Profiles are deterministic text pipelines — no model calls.
"""

from __future__ import annotations

import re
from typing import Protocol

GLYPH_DONE = "✓"  # ✓
GLYPH_ACTIVE = "▶"  # ▶
GLYPH_FAILED = "✗"  # ✗
GLYPH_PENDING = "◌"  # ◌
ARROW = "→"  # →

STATUS_GLYPHS = {
    "done": GLYPH_DONE,
    "active": GLYPH_ACTIVE,
    "failed": GLYPH_FAILED,
    "pending": GLYPH_PENDING,
}


class NotationProfile(Protocol):
    """A pluggable density profile."""

    @property
    def name(self) -> str: ...

    def legend(self) -> str:
        """One-time notation legend (≤120 tokens), emitted once per rope."""
        ...

    def densify(self, text: str) -> str:
        """Compress prose into profile notation. Deterministic."""
        ...


# Phrase-level rewrites applied before word-level rules. Order matters:
# longer phrases first so shorter substrings do not shadow them.
_PHRASE_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pat, re.IGNORECASE), rep)
    for pat, rep in (
        (r"\bit should be noted that\b", ""),
        (r"\bdue to the fact that\b", "∵"),
        (r"\bin order to\b", "to"),
        (r"\bas well as\b", "+"),
        (r"\bso that\b", "→"),
        (r"\bwhich (?:leads|led) to\b", "→"),
        (r"\b(?:leads|led) to\b", "→"),
        (r"\bresult(?:s|ed)? in\b", "→"),
        (r"\bwhich (?:causes|caused)\b", "→"),
        (r"\bcaus(?:es|ed|ing)\b", "→"),
        (r"\bbecause of\b", "∵"),
        (r"\bbecause\b", "∵"),
        (r"\bsince\b", "∵"),
        (r"\bis (?:now )?(?:completed?|finished|done)\b", GLYPH_DONE),
        (r"\b(?:has|have) been (?:completed?|finished|done)\b", GLYPH_DONE),
        (r"\bwas (?:completed?|finished|done)\b", GLYPH_DONE),
        (r"\b(?:completed?|finished)\b", GLYPH_DONE),
        (r"\bsuccessfully\b", ""),
        (r"\b(?:is|are|was|were) (?:currently )?(?:failing|broken)\b", GLYPH_FAILED),
        (r"\bfail(?:s|ed|ing)?\b", GLYPH_FAILED),
        (r"\b(?:is|are) (?:currently )?in progress\b", GLYPH_ACTIVE),
        (r"\bin progress\b", GLYPH_ACTIVE),
        (r"\bcurrently working on\b", GLYPH_ACTIVE),
        (r"\b(?:is|are) (?:still )?pending\b", GLYPH_PENDING),
        (r"\bpending\b", GLYPH_PENDING),
        (r"\bwaiting (?:on|for)\b", GLYPH_PENDING),
        (r"\bdecided to use\b", "chose"),
        (r"\bwithout\b", "w/o"),
        (r"\bwith\b", "w/"),
    )
)

# Filler words removed entirely.
_FILLER = re.compile(
    r"\b(?:the|a|an|really|very|just|simply|basically|actually|that|which|"
    r"of course|please|note that|currently|now|then|also|still|there (?:is|are)|"
    r"it (?:is|was)|this (?:is|was)|in fact|as expected|going forward|"
    r"we|us|our)\b",
    re.IGNORECASE,
)

# Weak copulas / auxiliaries dropped for telegraphic style.
_COPULA = re.compile(
    r"\b(?:is|are|was|were|has been|have been|had been|will be|being|"
    r"have|has|had|does|do|did|should be|must be|can be)\b",
    re.IGNORECASE,
)

# Word-level abbreviations declared in the legend.
_ABBREV: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{pat}\b", re.IGNORECASE), rep)
    for pat, rep in (
        (r"configurations?", "cfg"),
        (r"implementations?", "impl"),
        (r"implement(?:ed|ing)?", "impl"),
        (r"functions?", "fn"),
        (r"databases?", "db"),
        (r"environments?", "env"),
        (r"dependenc(?:y|ies)", "deps"),
        (r"repositor(?:y|ies)", "repo"),
        (r"director(?:y|ies)", "dir"),
        (r"applications?", "app"),
        (r"authentications?", "auth"),
        (r"documentation", "docs"),
        (r"documents?", "docs"),
        (r"requirements?", "reqs"),
        (r"performance", "perf"),
        (r"migrations?", "migr"),
        (r"and", "+"),
    )
)

_MULTISPACE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,;:.→])")
_SENTENCE_END = re.compile(r"\.\s+")


def _telegraphic(text: str) -> str:
    out = text
    for pattern, rep in _PHRASE_RULES:
        out = pattern.sub(rep, out)
    out = _FILLER.sub("", out)
    out = _COPULA.sub("", out)
    for pattern, rep in _ABBREV:
        out = pattern.sub(rep, out)
    out = _SENTENCE_END.sub("; ", out)
    out = out.rstrip(". ")
    out = _MULTISPACE.sub(" ", out)
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)
    return out.strip()


class SymbolicEnProfile:
    """Default profile: telegraphic English with glyphs and arrow notation."""

    @property
    def name(self) -> str:
        return "symbolic-en"

    def legend(self) -> str:
        return (
            f"glyphs: {GLYPH_DONE}done {GLYPH_ACTIVE}active {GLYPH_FAILED}failed "
            f"{GLYPH_PENDING}pending {ARROW}yields ∵because +and w/=with w/o=without\n"
            "abbr: cfg=config impl=implementation fn=function db=database env=environment "
            "deps=dependencies repo=repository dir=directory app=application "
            "auth=authentication docs=documentation reqs=requirements perf=performance "
            "migr=migration\n"
            "rec: D#|date|decision|reason K#|topic|vec-id P0..P3=priority"
        )

    def densify(self, text: str) -> str:
        return _telegraphic(text)


# cjk-dense maps frequent operational words onto single CJK characters on top
# of the symbolic-en pipeline. Token savings vary by tokenizer — README
# reports measured o200k_base counts; do not assume savings transfer.
_CJK_MAP: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{pat}\b", re.IGNORECASE), rep)
    for pat, rep in (
        (r"files?", "档"),  # 档
        (r"tests?", "测"),  # 测
        (r"errors?", "错"),  # 错
        (r"fix(?:es|ed)?", "修"),  # 修
        (r"add(?:s|ed)?", "加"),  # 加
        (r"servers?", "服"),  # 服
        (r"deploy(?:s|ed|ment)?", "部"),  # 部
    )
)


class CjkDenseProfile:
    """Optional profile: symbolic-en plus CJK single-character substitutions."""

    def __init__(self) -> None:
        self._base = SymbolicEnProfile()

    @property
    def name(self) -> str:
        return "cjk-dense"

    def legend(self) -> str:
        cjk = "cjk: 档file 测test 错error 修fix 加add 服server 部deploy"
        return self._base.legend() + "\n" + cjk

    def densify(self, text: str) -> str:
        out = self._base.densify(text)
        for pattern, rep in _CJK_MAP:
            out = pattern.sub(rep, out)
        return out


_PROFILES: dict[str, NotationProfile] = {
    "symbolic-en": SymbolicEnProfile(),
    "cjk-dense": CjkDenseProfile(),
}


def get_profile(name: str) -> NotationProfile:
    """Look up a registered profile by name."""
    try:
        return _PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(_PROFILES))
        raise KeyError(f"unknown notation profile {name!r}; known: {known}") from None


def register_profile(profile: NotationProfile) -> None:
    """Register a custom profile (overwrites an existing name)."""
    _PROFILES[profile.name] = profile
