"""Zero-network guarantee: bundled tokenizer + socket guard."""

from __future__ import annotations

import socket
from collections.abc import Iterator

import jumping_rope.tokens  # sets TIKTOKEN_CACHE_DIR to the bundled vocabulary
import pytest

jumping_rope.tokens.get_encoder()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def blocked(self: socket.socket, address: object) -> None:
        raise RuntimeError(f"test attempted network connection to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    yield
