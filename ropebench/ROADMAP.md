# ROADMAP — ironing out Jumping Rope through measurement

The development loop this repo drives: **benchmark → localize the failure →
fix in `jumping-rope` → re-run the benchmark as the regression gate.**
Every phase has an exit criterion measured by this harness, not by vibes.

## Phase 0 — mechanics + adversarial hardening ✅ (done)

- 52 mechanics tests + 29 adversarial tests in `jumping-rope`
  (`ADVERSARIAL_REPORT.md` there: 8 broken → 8 fixed, 6 held).
- Known carried limits: hash-embedder paraphrase recall (A12, 67% under
  distractors), keyring reachability beyond 3 generations for literal
  readers (A1 residual).

## Phase 1 — information availability (this repo) ✅ (done)

Deterministic scripted-reader sweep, 3 seeds × 80 turns × 4 regimes:

| Regime | Acc | long-distance | tokens | acc/10k tok |
|---|---|---|---|---|
| full-history | 100% | 100% | 280,455 | 3.6 |
| truncate | 91% | 67% | 201,517 | 4.5 |
| summary | 79% | 24% | 192,357 | 4.1 |
| **rope (bound)** | **95%** | **100%** | **148,607** | **6.4** |
| rope-unbound | 100% | 100% | 498,828 | 2.0 |

*(v1.1 update: rope regimes now use the system's own notation — densify
lifted bound decision recall 79% → 83%; the unbound row measures perfect
recall at honest cost, see B4/B5.)*

**Findings to fix (the "major bugs" queue):**

- **B1 — decision recall is the weak cell (79%).** DECISIONS demote first
  under budget pressure, so medium-distance decision probes ride entirely on
  TurboVec semantic recall, which misses on partial-overlap queries. Fact
  and status recall are 100%.
- **B2 — medium-distance dip (83%).** Items demoted recently enough to be
  out of the rope but crowded in the store by fresher records. Same root
  cause as B1: retrieval recall, not rope structure.
- **B3 — hash-embedder paraphrase blindness** (= jumping-rope A12).
- **B4 — per-record structural overhead.** Every DECISIONS line carries a
  full ISO date (~7 tokens) plus a reason field; on the unbound rope this
  compounds into ~1.8× the raw oracle's cost on pre-distilled streams.
  Candidates: MMDD dates, date elision when unchanged from previous line.
- **B5 — the scenario under-sells unbound mode.** The bench feeds
  pre-distilled events; real sessions are chatty transcripts where the
  same facts arrive wrapped in 5–10× filler. A "chatty scenario" variant
  (events embedded in conversational padding, streaming eviction in the
  loop) would measure unbound mode's real economics (adapter tests: 17–18%
  payloads).

## Phase 2 — information use (live model sweep) — NEXT, needs one decision

Same harness, real model via `--mode live` (any OpenAI-compatible endpoint).
Adds the live-only metrics: hallucinated-continuity rate (answers not
grounded in any tier), retrieval-tool discipline (does the model actually
emit `RETRIEVE:` on cache misses), instruction adherence to the rope legend.

- **Blocked on:** endpoint/model choice + budget cap (recommended: the
  Contabo LiteLLM gateway with its existing rpm/day guardrails; one full
  sweep ≈ 300–500 calls, single bounded run, no loops).
- **Exit criterion:** live rope ≥ 90% of live full-history accuracy at
  ≤ 35% of its tokens; hallucination rate < 5%; results committed to
  `results/` and pinned in the README.

## Phase 3 — fix B1–B3 in jumping-rope

1. **Hybrid retrieval** (targets B1/B2 directly): add a lexical term-match
   channel next to cosine search in TurboVec (`search()` merging exact-term
   hits with vector hits before ranking). Predicted effect: decision recall
   → ~100% in Phase 1 re-run.
2. **Decision-aware demotion:** demote DECISIONS by age *but* pin the N
   most-referenced/most-recent decisions above DELTA in the demotion order,
   or give decisions a compact `D#` digest line before full demotion.
3. **Embedder upgrade path:** make `SentenceTransformerEmbedder` a
   first-class documented option for deployments; benchmark it in live mode.
4. Re-run Phase 1 + adversarial suite after each change — both must stay
   green (`test_regime_ordering_claims` is the regression gate).

**Exit criterion:** scripted sweep ≥ 97% overall for rope, no cell < 90%,
efficiency lead intact.

## Phase 4 — richer failure probes

- Add probe kinds the current scenario lacks: **re-litigation** (does the
  model contradict a recorded decision?), **no-regression** (does it redo ✓
  work?), **stale-state** (fact superseded mid-session — does it answer with
  the newest version?). Supersession probes will stress DELTA's
  newest-wins map and rope STATE updates.
- Multi-session probes: kill the session, restart from disk (crash-recovery
  path from adversarial A9), continue the scenario, re-probe.

**Exit criterion:** new probe kinds ≥ 90% for rope in scripted mode.

## Phase 5 — real-workload replay + release

- Replay real agent transcripts (Claude Code sessions via the
  jumping-rope skill) through the regimes; score with planted questions
  authored per-transcript.
- Merge both jumping-rope PRs, re-pin this repo's dependency from the
  `test/adversarial-v1` branch to `main`, cut jumping-rope v1.1 with README
  claims backed by RopeBench numbers, and publish both packages.

**Exit criterion:** README of jumping-rope cites only measured numbers;
one external-model live sweep reproduced by someone other than the author
(fork-ready: this repo has no machine-specific paths or keys).

## Standing decisions needed from the owner

1. Phase 2 endpoint + spend cap (gateway `meridian-deep` vs OpenRouter key).
2. Whether Phase 3's hybrid retrieval should change the default `search()`
   behavior or ship behind a flag (recommendation: default on — it is
   strictly additive recall).
3. When to merge `jumping-rope` PR #1/#2 so the dependency pin moves to main.
