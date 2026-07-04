"""T7 — distractor anti-fragility: exact addressing vs semantic search under
near-duplicate interference.

Near-duplicate facts share almost every token ("the amber anchor pipeline is
pinned to build argon-XXXX ...") and differ only in the distinctive value. A
semantic retriever cannot separate them — the value is a single token in a sea
of shared context — so as N near-duplicates flood the vault, top-k recall of a
*specific* target collapses toward chance (k / (N+1)). The rope gives every
archived fact a turn-stamped KEYS handle ("t{turn}·topic → key"); an exact
content-addressed fetch is immune to how crowded the neighbourhood is.

This script measures both recall curves. No LLM, no network.
"""

from __future__ import annotations

import random
import statistics
import tempfile
from pathlib import Path

from jumping_rope.notation import get_profile
from jumping_rope.turbovec import TurboVec

SESSION = "t7"
_ADJ = ["amber", "brisk", "coral", "dusky", "ember", "frosted", "gilded",
        "hollow", "ionic", "jasper", "kelp", "lunar", "mossy", "nickel",
        "onyx", "pluvial", "quartz", "russet", "slate", "umber"]
_NOUN = ["anchor", "baffle", "crank", "dynamo", "eyelet", "flange", "gasket",
         "hinge", "impeller", "jig", "keel", "lattice", "manifold", "nozzle",
         "orifice", "pawl", "quill", "ratchet", "spar", "trunnion"]


def _fact(prof: object, adj: str, noun: str, value: str) -> str:
    text = f"the {adj} {noun} pipeline is pinned to build {value} until further notice"
    return prof.densify(text)  # type: ignore[attr-defined]


def _subject_query(prof: object, adj: str, noun: str) -> str:
    # What the model asks with — the fact's subject, NOT the value it's after.
    return prof.densify(  # type: ignore[attr-defined]
        f"what build is the {adj} {noun} pipeline pinned to")


def run(n_targets: int = 20, distractors: tuple[int, ...] = (0, 2, 4, 8, 16, 32, 64),
        k: int = 3, seed: int = 0, profile: str = "symbolic-en") -> dict[int, dict[str, float]]:
    prof = get_profile(profile)
    rng = random.Random(seed)
    out: dict[int, dict[str, float]] = {}
    for n in distractors:
        flat_hits: list[int] = []
        rope_hits: list[int] = []
        for t in range(n_targets):
            adj, noun = _ADJ[t % len(_ADJ)], _NOUN[t % len(_NOUN)]
            target_val = f"argon-{1000 + t}"
            db = Path(tempfile.mkdtemp(prefix="t7-")) / "v.db"
            vault = TurboVec(db, force_fallback=True)
            # The one real fact + its turn-stamped exact handle (the KEYS line).
            target_key = vault.put(
                session_id=SESSION, jump_index=0, section="ARCHIVE",
                content=_fact(prof, adj, noun, target_val), turn=t,
            )
            # N near-duplicate distractors: same subject, different value.
            for d in range(n):
                dval = f"argon-{rng.randint(2000, 9999)}"
                vault.put(session_id=SESSION, jump_index=0, section="ARCHIVE",
                          content=_fact(prof, adj, noun, dval), turn=1000 + d)
            query = _subject_query(prof, adj, noun)
            # Flat blob: semantic-only. Does target value survive into top-k?
            hits = vault.search(query, k=k, session_id=SESSION)
            blob = " ".join(h.content for h in hits)
            flat_hits.append(int(target_val in blob))
            # Rope: exact content-addressed fetch via the KEYS handle.
            rec = vault.get(target_key)
            rope_hits.append(int(rec is not None and target_val in rec.content))
            vault.close()
        out[n] = {
            "flat": statistics.mean(flat_hits),
            "rope": statistics.mean(rope_hits),
            "chance": min(1.0, k / (n + 1)),
        }
    return out


def aggregate(profile: str, seeds: int = 8, n_targets: int = 20) -> dict[int, dict[str, float]]:
    """Mean flat/rope recall over ``seeds`` × ``n_targets`` per distractor count."""
    acc: dict[int, dict[str, list[float]]] = {}
    for s in range(seeds):
        r = run(n_targets=n_targets, seed=s, profile=profile)
        for n, row in r.items():
            b = acc.setdefault(n, {"flat": [], "rope": [], "chance": []})
            for key in b:
                b[key].append(row[key])
    return {n: {k: statistics.mean(v) for k, v in b.items()} for n, b in acc.items()}


if __name__ == "__main__":
    import sys

    seeds = 8
    for profile in ("symbolic-en", "ai-native"):
        res = aggregate(profile, seeds=seeds)
        print(f"\n### profile = {profile}  ({seeds} seeds × 20 targets)")
        print(f"{'N distractors':>13} | {'flat semantic':>13} | {'rope exact':>10} "
              f"| {'chance k/(N+1)':>14}")
        print("-" * 60)
        for n, row in res.items():
            print(f"{n:>13} | {row['flat']:>12.0%} | {row['rope']:>9.0%} "
                  f"| {row['chance']:>13.0%}")
    sys.exit(0)
