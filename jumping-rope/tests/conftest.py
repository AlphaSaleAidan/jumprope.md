"""Shared fixtures. Enforces the zero-network guarantee for the whole suite:

- tiktoken reads the bundled o200k_base vocabulary (TIKTOKEN_CACHE_DIR)
- any attempt to open a real socket raises immediately
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

_BUNDLED = Path(__file__).resolve().parent.parent / "jumping_rope" / "_data" / "tiktoken_cache"
os.environ["TIKTOKEN_CACHE_DIR"] = str(_BUNDLED)


class _NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail loudly if any test tries to reach the network."""
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: object) -> None:
        host = address[0] if isinstance(address, tuple) else str(address)
        if isinstance(host, str) and host not in ("localhost", "127.0.0.1", "::1"):
            raise _NetworkBlocked(f"test attempted network connection to {address!r}")
        real_connect(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield


@pytest.fixture()
def clock() -> Iterator[object]:
    """Deterministic monotonic clock for reproducible ropes."""

    class Clock:
        def __init__(self) -> None:
            self.n = 0

        def __call__(self) -> str:
            self.n += 1
            return f"2026-07-03T00:{self.n // 60:02d}:{self.n % 60:02d}Z"

    yield Clock()
