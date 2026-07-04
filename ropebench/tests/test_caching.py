"""Hermetic tests for the OpenAI-compat client cache (S0)."""

from __future__ import annotations

from pathlib import Path

from ropebench.models import OpenAICompatModel

CONTEXT = "the amber anchor pipeline is pinned to build argon-4412 until further notice"


def test_cache_avoids_second_call(tmp_path: Path) -> None:
    calls = {"n": 0}

    def chat_fn(messages: list[dict[str, str]]) -> str:
        calls["n"] += 1
        return "the pipeline is pinned to argon-4412"

    model = OpenAICompatModel(
        base_url="http://x/v1", model="haiku", chat_fn=chat_fn,
        cache_dir=tmp_path / "cache",
    )
    q = "What build is the amber anchor pipeline pinned to?"
    a1 = model.answer(CONTEXT, q)
    a2 = model.answer(CONTEXT, q)  # identical payload → cache hit
    assert a1.text == a2.text
    assert calls["n"] == 1, "second identical call must be served from cache"
    assert model.cache_hits == 1 and model.cache_misses == 1


def test_different_payload_misses(tmp_path: Path) -> None:
    calls = {"n": 0}

    def chat_fn(messages: list[dict[str, str]]) -> str:
        calls["n"] += 1
        return "argon-4412"

    model = OpenAICompatModel(
        base_url="http://x/v1", model="haiku", chat_fn=chat_fn,
        cache_dir=tmp_path / "cache",
    )
    model.answer(CONTEXT, "question one?")
    model.answer(CONTEXT, "a different question?")
    assert calls["n"] == 2
