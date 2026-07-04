"""Jumping Rope: two-tier context-handoff system for LLM sessions.

Tier 1 is a token-dense rope file (ROPE.md) under a hard token budget; tier 2
is TurboVec, an embedded vector store holding everything demoted out of the
rope. On a jump (context clear) the rope is the only context carried over;
missing detail is fetched back from TurboVec like a cache miss.
"""

from .compactor import Compactor, RopeBudgetError
from .notation import (
    AiNativeProfile,
    CjkDenseProfile,
    NotationProfile,
    SymbolicEnProfile,
    get_profile,
    register_profile,
)
from .rope import RopeFile, RopeParseError, RopeValidationError
from .session import JumpConfig, JumpingRopeSession
from .tokens import count_tokens
from .turbovec import (
    Embedder,
    HashEmbedder,
    SentenceTransformerEmbedder,
    TurboVec,
    VecRecord,
    format_retrieved,
)

__version__ = "1.0.0"

__all__ = [
    "AiNativeProfile",
    "CjkDenseProfile",
    "Compactor",
    "Embedder",
    "HashEmbedder",
    "JumpConfig",
    "JumpingRopeSession",
    "NotationProfile",
    "RopeBudgetError",
    "RopeFile",
    "RopeParseError",
    "RopeValidationError",
    "SentenceTransformerEmbedder",
    "SymbolicEnProfile",
    "TurboVec",
    "VecRecord",
    "__version__",
    "count_tokens",
    "format_retrieved",
    "get_profile",
    "register_profile",
]
