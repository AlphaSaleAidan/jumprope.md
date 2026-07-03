"""A12 — HashEmbedder collision probe: near-duplicate distractors.

200 distractors differ from the target by one critical token (port numbers,
negation). Exact-key retrieval must be immune; the semantic top-3 hit rate
under distractors is MEASURED and documented — it is the honest limit of
hash embeddings (see README limitations).
"""

from __future__ import annotations

from pathlib import Path

from jumping_rope.turbovec import TurboVec

TARGET = "the sentinel service keeps port 4000 open for the gateway handshake"

QUERIES = {
    "verbatim": TARGET,
    "near-verbatim": "sentinel service port 4000 open gateway handshake",
    "paraphrase": "which port does the sentinel service keep open for the gateway",
}


def build_distractor_store(tmp_path: Path) -> tuple[TurboVec, str]:
    store = TurboVec(tmp_path / "a12.db", force_fallback=True)
    target_key = store.put(
        session_id="a12", jump_index=0, section="OPEN", content=TARGET
    )
    n = 0
    for port in range(4001, 4101):  # 100 one-number-off distractors
        store.put(
            session_id="a12", jump_index=0, section="OPEN",
            content=f"the sentinel service keeps port {port} open for the gateway handshake",
        )
        n += 1
    for port in range(4000, 4100):  # 100 negation distractors (incl. port 4000!)
        store.put(
            session_id="a12", jump_index=0, section="OPEN",
            content=f"the sentinel service keeps port {port} closed for the gateway handshake",
        )
        n += 1
    assert n == 200
    return store, target_key


def test_a12_exact_key_immune_to_distractors(tmp_path: Path) -> None:
    store, target_key = build_distractor_store(tmp_path)
    record = store.get(target_key)
    assert record is not None
    assert record.content == TARGET, "exact-key retrieval returned a distractor"
    store.close()


def test_a12_semantic_hit_rate_measured(tmp_path: Path) -> None:
    """Documents (not gates) the hash-embedding limit. Only the verbatim
    query is asserted; the others are measured for the report."""
    store, _ = build_distractor_store(tmp_path)
    results: dict[str, bool] = {}
    for name, query in QUERIES.items():
        top3 = store.search(query, k=3, session_id="a12")
        results[name] = any(r.content == TARGET for r in top3)
    hit_rate = sum(results.values()) / len(results)
    print(f"\n[a12] semantic top-3 under 200 near-duplicates: {results} "
          f"(hit rate {hit_rate:.0%})")
    # One-token differences are near-invisible to bag-of-ngram hashing:
    # the verbatim query itself must at least surface the true record.
    assert results["verbatim"], "verbatim query lost its own record in top-3"
    store.close()
