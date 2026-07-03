"""Token counting against the reference tokenizer (tiktoken o200k_base).

The o200k_base BPE vocabulary is bundled with the package under
``_data/tiktoken_cache`` so counting works with zero network access
(tiktoken otherwise downloads the vocabulary on first use).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol

ENCODING_NAME = "o200k_base"
_BUNDLED_CACHE = Path(__file__).resolve().parent / "_data" / "tiktoken_cache"


class TokenEncoder(Protocol):
    """Minimal encoder surface Jumping Rope needs."""

    def encode(self, text: str) -> list[int]: ...


@lru_cache(maxsize=1)
def get_encoder() -> TokenEncoder:
    """Return the o200k_base encoder, using the bundled vocabulary cache."""
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(_BUNDLED_CACHE))
    import tiktoken

    encoder: TokenEncoder = tiktoken.get_encoding(ENCODING_NAME)
    return encoder


def count_tokens(text: str) -> int:
    """Count tokens in ``text`` under o200k_base."""
    if not text:
        return 0
    return len(get_encoder().encode(text))


def over_budget(text: str, budget: int) -> bool:
    """True when ``text`` exceeds ``budget`` tokens."""
    return count_tokens(text) > budget
