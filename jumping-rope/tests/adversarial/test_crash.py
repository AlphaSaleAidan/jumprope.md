"""A9–A11 — crash and concurrency attacks."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.rope import RopeFile
from jumping_rope.turbovec import TurboVec

FACTS = [f"FACT-{c} the {w} assembly is load-bearing" for c, w in
         zip("ABCDE", ["gilded flange", "hollow keel", "amber gasket",
                       "mossy dynamo", "ionic lattice"], strict=True)]
FILLER = "filler {i} verbose padding sentence to overflow the small budget quickly"


def fact_locations(session: JumpingRopeSession, fact: str) -> list[str]:
    """Where does a fact currently live? ('rope' and/or 'store')."""
    places = []
    if fact in session.rope.render():
        places.append("rope")
    matches = [
        r for r in session.store.dump()
        if fact in r.content and r.section != "KEYS"
    ]
    places.extend(["store"] * len(matches))
    return places


class Bomb(RuntimeError):
    pass


def make_bombed_session(
    tmp_path: Path, clock: Callable[[], str], allow_puts: int
) -> JumpingRopeSession:
    session = JumpingRopeSession(
        tmp_path,
        session_id="crash",
        config=JumpConfig(rope_budget_tokens=300),
        force_fallback=True,
        clock=clock,
    )
    real_put = session.store.put
    counter = {"n": 0}

    def exploding_put(**kwargs: object) -> str:
        if counter["n"] >= allow_puts:
            raise Bomb(f"simulated disk failure after {allow_puts} writes")
        counter["n"] += 1
        return real_put(**kwargs)  # type: ignore[arg-type]

    session.store.put = exploding_put  # type: ignore[method-assign]
    session._real_put = real_put  # type: ignore[attr-defined]
    return session


@pytest.mark.parametrize("allow_puts", [0, 1, 3])
def test_a9_kill_mid_jump_strands_no_fact(
    tmp_path: Path, clock: Callable[[], str], allow_puts: int
) -> None:
    data_dir = tmp_path / f"crash-{allow_puts}"
    session = make_bombed_session(data_dir, clock, allow_puts)
    recorded: list[str] = []
    for fact in FACTS:
        session.record_event("open", fact, priority=2, densify=False)
        recorded.append(fact)

    with pytest.raises(Bomb):
        for i in range(30):
            content = FILLER.format(i=i)
            recorded.append(content)  # appended to the rope before enforce runs
            session.record_event("decision", content, reason="x", densify=False)

    # 1. The rope on disk must never be left unparseable.
    disk_text = (data_dir / "ROPE.md").read_text(encoding="utf-8")
    RopeFile.parse(disk_text)

    # 2. The crashed in-process session must not have lost ANY recorded
    #    content: a caller that catches the error and keeps going must not
    #    persist a rope from which an event silently vanished.
    session.store.put = session._real_put  # type: ignore[attr-defined, method-assign]
    for content in recorded:
        assert fact_locations(session, content), f"{content!r} lost from live session"
    session.close()

    # 3. Recovery: restart from disk, complete the interrupted compaction via
    #    a jump. Every planted fact ends in EXACTLY one of rope / TurboVec.
    recovered = JumpingRopeSession(data_dir, force_fallback=True, clock=clock)
    recovered.jump()
    for fact in FACTS:
        places = fact_locations(recovered, fact)
        assert places, f"{fact!r} permanently stranded"
        assert len(places) == 1, f"{fact!r} duplicated: {places}"
    recovered.close()


def test_a10_double_jump_is_clean_and_deduped(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = JumpingRopeSession(
        tmp_path / "dj",
        session_id="dj",
        config=JumpConfig(rope_budget_tokens=300),
        force_fallback=True,
        clock=clock,
    )
    for i in range(12):
        session.record_event(
            "decision", FILLER.format(i=i), reason="x", densify=False
        )
    records_after_events = int(session.store.stats()["records"])  # type: ignore[call-overload]

    first = session.jump()
    second = session.jump()  # no intervening events
    assert session.rope.jump_count == 2
    RopeFile.parse(first)
    RopeFile.parse(second)
    # Second jump demotes nothing new — no duplicate TurboVec records.
    assert int(session.store.stats()["records"]) == records_after_events  # type: ignore[call-overload]
    session.close()


def test_a10_put_is_idempotent_by_content(tmp_path: Path) -> None:
    """Key stability: re-storing identical content (crash-retry path) must
    not create duplicate records."""
    store = TurboVec(tmp_path / "idem.db", force_fallback=True)
    k1 = store.put(session_id="s", jump_index=0, section="OPEN", content="same content")
    k2 = store.put(session_id="s", jump_index=1, section="OPEN", content="same content")
    assert k1 == k2, "same (session, section, content) must map to a stable key"
    assert int(store.stats()["records"]) == 1  # type: ignore[call-overload]
    # Different session or section → different record.
    k3 = store.put(session_id="other", jump_index=0, section="OPEN", content="same content")
    assert k3 != k1
    assert int(store.stats()["records"]) == 2  # type: ignore[call-overload]
    store.close()


def test_a11_two_sessions_one_store_two_threads(tmp_path: Path) -> None:
    store = TurboVec(tmp_path / "shared.db", force_fallback=True)
    errors: list[BaseException] = []
    OPS = 50

    def worker(session_id: str, salt: str) -> None:
        try:
            for i in range(OPS):
                store.put(
                    session_id=session_id,
                    jump_index=0,
                    section="OPEN",
                    content=f"{salt} record {i} about the {salt} subsystem",
                )
                hits = store.search(f"{salt} subsystem", k=3, session_id=session_id)
                assert all(h.session_id == session_id for h in hits)
        except BaseException as exc:  # noqa: BLE001 - collect for main thread
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("sess-a", "alpha")),
        threading.Thread(target=worker, args=("sess-b", "bravo")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"uncaught errors under concurrency: {errors!r}"
    assert int(store.stats()["records"]) == 2 * OPS  # type: ignore[call-overload]
    # Zero cross-session leakage.
    for sid, salt in (("sess-a", "alpha"), ("sess-b", "bravo")):
        hits = store.search("record subsystem", k=10, session_id=sid)
        assert hits and all(salt in h.content for h in hits)
    store.close()
