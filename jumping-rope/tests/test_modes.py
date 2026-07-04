"""Bound vs unbound modes, streaming transcript eviction, ai-native
notation, and turn provenance."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from jumping_rope import AiNativeProfile, JumpConfig, JumpingRopeSession
from jumping_rope.handoff import apply_streaming_policy, history_tokens
from jumping_rope.rope import RopeFile
from jumping_rope.tokens import count_tokens

_CODE = re.compile(r"§[a-z]{1,2}")
FAT_DECISION = (
    "we decided to route the {n} payment retries through the fallback "
    "acquirer because the primary acquirer throttles bursts aggressively"
)


def test_mode_helpers() -> None:
    assert JumpConfig().mode == "bound"
    assert JumpConfig.bound(rope_budget_tokens=800).mode == "bound"
    assert JumpConfig.unbound().mode == "unbound"
    assert JumpConfig(rope_budget_tokens=0).mode == "unbound"  # 0 normalizes
    assert JumpConfig(rope_budget_tokens=None).unbounded


def test_unbound_rope_never_demotes(tmp_path: Path, clock: Callable[[], str]) -> None:
    session = JumpingRopeSession(
        tmp_path / "ub",
        session_id="ub",
        config=JumpConfig.unbound(),
        force_fallback=True,
        clock=clock,
    )
    for i in range(60):
        session.record_event("decision", FAT_DECISION.format(n=i), reason="load")
    rendered = session.rope.render()
    # Everything stays on the rope verbatim — no demotion, no keys, no error.
    assert len(session.rope.decisions) == 60
    assert not session.rope.keys
    assert int(session.store.stats()["records"]) == 0  # type: ignore[call-overload]
    assert count_tokens(rendered) > 2_000  # allowed to exceed the old cap
    carried = session.jump()  # jumps still work; the rope is the context
    assert RopeFile.parse(carried).jump_count == 1
    session.close()


def test_bound_mode_unchanged(tmp_path: Path, clock: Callable[[], str]) -> None:
    session = JumpingRopeSession(
        tmp_path / "b",
        session_id="b",
        config=JumpConfig.bound(rope_budget_tokens=400),
        force_fallback=True,
        clock=clock,
    )
    for i in range(30):
        session.record_event("decision", FAT_DECISION.format(n=i), reason="load")
        assert count_tokens(session.rope.render()) <= 400
    assert int(session.store.stats()["records"]) > 0  # type: ignore[call-overload]
    session.close()


# -- streaming transcript eviction -------------------------------------------


def chat_turn(history: list[dict[str, str]], i: int) -> None:
    history.append(
        {"role": "user",
         "content": f"turn {i}: "
         + f"please reconcile ledger shard {i} against the vault and report "
         "any mismatched entries with their full account context. " * 12}
    )


def test_streaming_policy_evicts_covered_transcript(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = JumpingRopeSession(
        tmp_path / "stream",
        session_id="stream",
        config=JumpConfig.unbound(),
        force_fallback=True,
        clock=clock,
    )
    history: list[dict[str, str]] = []
    outbound_sizes: list[int] = []
    for i in range(12):
        chat_turn(history, i)
        outbound, _evicted = apply_streaming_policy(session, history)
        outbound_sizes.append(len(outbound))
        history.append({"role": "assistant", "content": f"reconciled shard {i} fine"})

    # After warm-up, outbound is flat: rope + current user (+ the one
    # not-yet-covered assistant reply) — NOT the growing history.
    assert outbound_sizes[-1] <= 3
    assert len(history) == 24
    naive = history_tokens(history)
    final_outbound, evicted = apply_streaming_policy(session, history)
    assert evicted
    assert final_outbound[0]["role"] == "system"
    assert final_outbound[0]["content"].startswith("# ROPE v1")
    assert history_tokens(final_outbound) < naive

    # The current user message is ALWAYS kept, covered or not.
    assert any(
        m["role"] == "user" and "turn 11" in str(m["content"])
        for m in final_outbound
    )

    # Nothing lost: every transcript message is recoverable from tier 2.
    for message in history:
        assert session.is_covered(str(message["content"])), message["content"]
    session.close()


def test_streaming_keys_match_context_log(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    """The key log lines up with the context log: every archived message
    gets a t{turn}-stamped K-line and a turn-stamped TurboVec record."""
    session = JumpingRopeSession(
        tmp_path / "prov",
        session_id="prov",
        config=JumpConfig.unbound(),
        force_fallback=True,
        clock=clock,
    )
    history: list[dict[str, str]] = []
    for i in range(4):
        chat_turn(history, i)
        apply_streaming_policy(session, history)
        history.append({"role": "assistant", "content": f"done with shard {i}"})

    stamped = [k for k in session.rope.keys if re.match(r"^t\d+·", k.topic)]
    assert stamped, "K-lines must carry t{turn} provenance stamps"
    for key_item in stamped:
        turn = int(key_item.topic.split("·")[0][1:])
        record = session.store.get(key_item.turbovec_id)
        assert record is not None
        assert record.turn == turn, "K-line stamp must match the record's turn"
    session.close()


# -- ai-native notation --------------------------------------------------------


def test_ai_native_promotes_recurring_phrases() -> None:
    profile = AiNativeProfile()
    phrase_text = "the payment reconciliation service rejected the batch again"
    outputs = [profile.densify(phrase_text) for _ in range(5)]
    assert _CODE.search(outputs[-1]), "recurring phrase should be dictionary-coded"
    assert "dict: §a=" in profile.legend()
    # Round trip: expanding restores the phrase words.
    expanded = profile.expand(outputs[-1])
    assert "§" not in expanded
    assert "reconciliation" in expanded


def test_ai_native_saves_tokens_on_repetitive_sessions(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    events = [
        f"the payment reconciliation service rejected batch {i} because the "
        "acquirer throttled the burst"
        for i in range(30)
    ]
    totals: dict[str, int] = {}
    for profile_name in ("symbolic-en", "ai-native"):
        session = JumpingRopeSession(
            tmp_path / profile_name,
            session_id=profile_name.replace("-", ""),
            config=JumpConfig.unbound(notation_profile=profile_name),
            force_fallback=True,
            clock=clock,
        )
        for event in events:
            session.record_event("decision", event, reason="repeat")
        totals[profile_name] = count_tokens(session.rope.render())
        session.close()
    print(f"\n[ai-native] rope tokens: {totals}")
    assert totals["ai-native"] < totals["symbolic-en"]


def test_ai_native_store_holds_decoded_content(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    """Demoted content must be expanded before storage so natural-language
    retrieval still works."""
    session = JumpingRopeSession(
        tmp_path / "dec",
        session_id="dec",
        config=JumpConfig.bound(rope_budget_tokens=400, notation_profile="ai-native"),
        force_fallback=True,
        clock=clock,
    )
    for i in range(25):
        session.record_event(
            "decision",
            f"the payment reconciliation service rejected batch {i} because the "
            "acquirer throttled the burst",
            reason="repeat",
        )
    records = session.store.dump()
    assert records, "budget pressure must have demoted something"
    assert all("§" not in r.content for r in records), "store must be decoded"
    hits = session.store.search("payment reconciliation rejected batch", k=3)
    assert hits and "reconciliation" in hits[0].content
    session.close()


def test_ai_native_dictionary_persists_across_restart(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    data_dir = tmp_path / "persist"
    session = JumpingRopeSession(
        data_dir, session_id="p",
        config=JumpConfig.unbound(notation_profile="ai-native"),
        force_fallback=True, clock=clock,
    )
    for _ in range(4):
        session.record_event(
            "decision", "the payment reconciliation service rejected the batch",
            reason="r",
        )
    legend_before = session.rope.legend
    assert "dict:" in legend_before
    session.close()

    reopened = JumpingRopeSession(data_dir, force_fallback=True, clock=clock)
    assert isinstance(reopened.profile, AiNativeProfile)
    assert reopened.profile.lexicon, "lexicon must survive restart"
    assert reopened.rope.legend == legend_before
    reopened.close()


# -- CLI ------------------------------------------------------------------------


def test_cli_unbound_mode(tmp_path: Path) -> None:
    def jrope(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "jumping_rope.cli", *args],
            cwd=tmp_path, capture_output=True, text=True, check=False,
        )

    assert jrope(["init", "--mode", "unbound"]).returncode == 0
    status = json.loads(jrope(["status"]).stdout)
    assert status["mode"] == "unbound"
    assert status["rope_budget_tokens"] is None


# -- retire: stacking the modes (work unbound, retire to bound) -----------------


def test_retire_compacts_unbound_session_to_bound(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    data_dir = tmp_path / "retire"
    session = JumpingRopeSession(
        data_dir, session_id="ret", config=JumpConfig.unbound(),
        force_fallback=True, clock=clock,
    )
    session.record_event("open", "RFACT the walnut governor caps retries at nine",
                         priority=2, densify=False)
    for i in range(60):
        session.record_event("decision", FAT_DECISION.format(n=i), reason="load")
    assert count_tokens(session.rope.render()) > 2_000
    jumps_before = session.rope.jump_count

    artifact = session.retire(budget_tokens=600)

    assert count_tokens(artifact) <= 600
    assert session.meta.config.mode == "bound"
    assert session.rope.jump_count == jumps_before + 1
    assert int(session.store.stats()["records"]) > 0  # type: ignore[call-overload]
    # Nothing lost: the demoted fact comes back from the vault.
    assert "walnut" in session.retrieve("walnut governor caps retries")
    session.close()

    # The retirement persists: reopening stays bound at the new budget.
    reopened = JumpingRopeSession(data_dir, force_fallback=True, clock=clock)
    assert reopened.meta.config.mode == "bound"
    assert reopened.meta.config.rope_budget_tokens == 600
    reopened.close()


def test_retire_rejects_unsatisfiable_budget(
    tmp_path: Path, clock: Callable[[], str]
) -> None:
    session = JumpingRopeSession(
        tmp_path / "r2", session_id="r2", config=JumpConfig.unbound(),
        force_fallback=True, clock=clock,
    )
    import pytest

    with pytest.raises(ValueError, match="minimum"):
        session.retire(budget_tokens=100)
    assert session.meta.config.mode == "unbound"  # unchanged on failure
    session.close()


def test_cli_retire(tmp_path: Path) -> None:
    def jrope(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "jumping_rope.cli", *args],
            cwd=tmp_path, capture_output=True, text=True, check=False,
        )

    assert jrope(["init", "--mode", "unbound"]).returncode == 0
    for i in range(40):
        assert jrope(["log", "decision", FAT_DECISION.format(n=i),
                      "--reason", "load"]).returncode == 0
    result = jrope(["retire", "--budget", "600"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("# ROPE v1")
    status = json.loads(jrope(["status"]).stdout)
    assert status["mode"] == "bound"
    assert status["rope_tokens"] <= 600
