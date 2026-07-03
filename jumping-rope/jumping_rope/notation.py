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
        """Notation legend, emitted once per rope (stateful profiles may
        extend it as their dictionary grows — it is never repeated)."""
        ...

    def densify(self, text: str) -> str:
        """Compress prose into profile notation. Deterministic."""
        ...

    def expand(self, text: str) -> str:
        """Reverse any dictionary coding (identity for stateless profiles).
        Applied before content reaches TurboVec so retrieval matches
        natural-language queries."""
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

    def expand(self, text: str) -> str:
        return text


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

    def expand(self, text: str) -> str:
        return text


# -- ai-native: adaptive dictionary coding ------------------------------------
# The rope is written FOR a model, not a human. On top of symbolic-en, this
# profile mines the session's own recurring phrases and assigns them short
# codes (§a, §b, …) declared once in the legend — LZ-style compression whose
# dictionary the reader model can see. Content is expanded back to natural
# language before it reaches TurboVec, so retrieval is unaffected.

_CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
_CODE_RE = re.compile(r"§[a-z]{1,2}")


def _nth_code(n: int) -> str:
    if n < 26:
        return f"§{_CODE_ALPHABET[n]}"
    return f"§{_CODE_ALPHABET[n // 26 - 1]}{_CODE_ALPHABET[n % 26]}"


class AiNativeProfile:
    """Stateful symbolic-en + per-session adaptive phrase dictionary."""

    PROMOTE_AT = 3  # occurrences before a phrase earns a code
    MAX_LEXICON = 24
    MAX_TRACKED = 300
    NGRAM_SIZES = (4, 3)
    MIN_PHRASE_CHARS = 12  # shorter phrases are not worth a legend entry

    def __init__(self) -> None:
        self._base = SymbolicEnProfile()
        self.lexicon: dict[str, str] = {}  # code -> phrase
        self._counts: dict[str, int] = {}

    @property
    def name(self) -> str:
        return "ai-native"

    def legend(self) -> str:
        base = self._base.legend()
        if not self.lexicon:
            return base
        entries = " ".join(f"{code}={phrase}" for code, phrase in self.lexicon.items())
        return base + "\ndict: " + entries

    # -- coding ---------------------------------------------------------------

    def _apply(self, text: str) -> str:
        for code, phrase in sorted(
            self.lexicon.items(), key=lambda kv: -len(kv[1])
        ):
            text = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", code, text)
        return text

    def _mine(self, text: str) -> None:
        words = [w for w in text.split() if "§" not in w and "|" not in w]
        for size in self.NGRAM_SIZES:
            for i in range(len(words) - size + 1):
                phrase = " ".join(words[i : i + size])
                if len(phrase) < self.MIN_PHRASE_CHARS:
                    continue
                self._counts[phrase] = self._counts.get(phrase, 0) + 1
        self._promote()
        if len(self._counts) > self.MAX_TRACKED:  # bounded state
            keep = sorted(self._counts.items(), key=lambda kv: -kv[1])
            self._counts = dict(keep[: self.MAX_TRACKED])

    @staticmethod
    def _bigrams(phrase: str) -> set[tuple[str, str]]:
        words = phrase.split()
        return set(zip(words, words[1:], strict=False))

    def _promote(self) -> None:
        if len(self.lexicon) >= self.MAX_LEXICON:
            return
        taken: set[tuple[str, str]] = set()
        for existing in self.lexicon.values():
            taken |= self._bigrams(existing)
        # Longest, most frequent candidates first; one entry per phrase
        # region (candidates sharing a word-bigram with an existing entry
        # are redundant — the longer entry already covers them).
        candidates = sorted(
            (
                (count, phrase)
                for phrase, count in self._counts.items()
                if count >= self.PROMOTE_AT and phrase not in self.lexicon.values()
            ),
            key=lambda t: (-t[0], -len(t[1]), t[1]),
        )
        for _count, phrase in candidates:
            if len(self.lexicon) >= self.MAX_LEXICON:
                break
            bigrams = self._bigrams(phrase)
            if bigrams & taken:
                continue
            self.lexicon[_nth_code(len(self.lexicon))] = phrase
            taken |= bigrams

    def densify(self, text: str) -> str:
        out = self._base.densify(text)
        out = self._apply(out)
        self._mine(out)
        return out

    def expand(self, text: str) -> str:
        for code, phrase in sorted(
            self.lexicon.items(), key=lambda kv: -len(kv[0])
        ):
            text = text.replace(code, phrase)
        return text

    # -- persistence ------------------------------------------------------------

    def state_dict(self) -> dict[str, object]:
        return {"lexicon": self.lexicon, "counts": self._counts}

    def load_state(self, state: dict[str, object]) -> None:
        lexicon = state.get("lexicon", {})
        counts = state.get("counts", {})
        if isinstance(lexicon, dict):
            self.lexicon = {str(k): str(v) for k, v in lexicon.items()}
        if isinstance(counts, dict):
            self._counts = {str(k): int(str(v)) for k, v in counts.items()}


_PROFILE_FACTORIES: dict[str, type] = {
    "symbolic-en": SymbolicEnProfile,
    "cjk-dense": CjkDenseProfile,
    "ai-native": AiNativeProfile,
}


def get_profile(name: str) -> NotationProfile:
    """Build a fresh profile instance by name (stateful profiles hold a
    per-session dictionary, so instances are never shared)."""
    try:
        profile: NotationProfile = _PROFILE_FACTORIES[name]()
        return profile
    except KeyError:
        known = ", ".join(sorted(_PROFILE_FACTORIES))
        raise KeyError(f"unknown notation profile {name!r}; known: {known}") from None


def register_profile(profile_cls: type) -> None:
    """Register a custom profile class (overwrites an existing name)."""
    _PROFILE_FACTORIES[profile_cls().name] = profile_cls
