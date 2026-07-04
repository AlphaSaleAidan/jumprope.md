"""§8.5 — TurboVec: put/get/search determinism, session isolation, fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from jumping_rope.turbovec import HashEmbedder, TurboVec

DOCS = [
    ("sess-a", "the walrus schema stores tungsten keys"),
    ("sess-a", "falcon queue drains into the basalt warehouse"),
    ("sess-a", "marble reports aggregate by fortnight"),
    ("sess-b", "the walrus schema stores tungsten keys in another session"),
    ("sess-b", "completely unrelated pastry recipe with cardamom"),
]


def fill(store: TurboVec) -> list[str]:
    return [
        store.put(session_id=sid, jump_index=0, section="DECISIONS", content=text)
        for sid, text in DOCS
    ]


@pytest.fixture(params=[False, True], ids=["auto-backend", "forced-fallback"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> TurboVec:
    return TurboVec(tmp_path / "tv.db", force_fallback=request.param)


def test_put_get_roundtrip(store: TurboVec) -> None:
    keys = fill(store)
    for key, (sid, text) in zip(keys, DOCS, strict=True):
        record = store.get(key)
        assert record is not None
        assert record.content == text
        assert record.session_id == sid
        assert record.tokens > 0
    assert store.get("no-such-key") is None


def test_search_relevance_and_determinism(store: TurboVec) -> None:
    fill(store)
    first = store.search("tungsten walrus keys", k=2)
    second = store.search("tungsten walrus keys", k=2)
    assert [r.key for r in first] == [r.key for r in second]  # deterministic
    assert "walrus" in first[0].content


def test_session_isolation(store: TurboVec) -> None:
    fill(store)
    hits = store.search("walrus tungsten", k=5, session_id="sess-b")
    assert hits and all(r.session_id == "sess-b" for r in hits)
    hits_a = store.search("walrus tungsten", k=5, session_id="sess-a")
    assert hits_a and all(r.session_id == "sess-a" for r in hits_a)


def test_forced_fallback_reports_backend(tmp_path: Path) -> None:
    store = TurboVec(tmp_path / "fb.db", force_fallback=True)
    assert store.using_vec_extension is False
    assert store.stats()["backend"] == "brute-force"
    fill(store)
    assert store.search("basalt warehouse", k=1)[0].content == DOCS[1][1]


def test_fallback_when_extension_import_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force the sqlite-vec import to explode; store must still work."""
    import builtins

    real_import = builtins.__import__

    def broken_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "sqlite_vec":
            raise ImportError("simulated missing extension")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", broken_import)
    store = TurboVec(tmp_path / "noext.db")
    assert store.using_vec_extension is False
    fill(store)
    assert "walrus" in store.search("walrus keys", k=1)[0].content


def test_backends_agree_on_best_match(tmp_path: Path) -> None:
    """Extension and fallback paths must agree on the clear winner.

    (Full-ranking equality is not asserted: float32 SQL vs float64 Python
    produce different tie-breaks among near-zero scores.)
    """
    fast = TurboVec(tmp_path / "fast.db")
    slow = TurboVec(tmp_path / "slow.db", force_fallback=True)
    fill(fast)
    fill(slow)
    q = "fortnight marble aggregate"
    fast_top = fast.search(q, k=3)
    slow_top = slow.search(q, k=3)
    assert len(fast_top) == len(slow_top) == 3
    assert fast_top[0].content == slow_top[0].content == DOCS[2][1]


def test_hash_embedder_deterministic_and_normalized() -> None:
    emb = HashEmbedder(dim=256)
    a = emb.embed("the falcon queue drains nightly")
    b = emb.embed("the falcon queue drains nightly")
    assert a == b
    assert len(a) == 256
    norm = sum(v * v for v in a) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_stats_shape(store: TurboVec) -> None:
    fill(store)
    stats = store.stats()
    assert stats["records"] == len(DOCS)
    assert stats["sessions"] == 2
    assert stats["embedder"] == "HashEmbedder"
