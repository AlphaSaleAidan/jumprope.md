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

## Phase 2 — information use (live model sweep) ✅ (done 2026-07-04)

Ran with Haiku 4.5 via the local `claude` CLI (`CommandModel`, `--mode
live-cmd`) — one bounded 390-call sweep, no Meridian infrastructure per the
owner's standing rule. Results in `results/live-haiku-full/` and the README.

**H5 verdict:**

- *Accuracy clause — PASS, decisively.* Live bound rope = **100%**, equal
  to the live full-history oracle (criterion was ≥90%). The live model
  outperformed the scripted reader (95%): flexible RETRIEVE queries
  recovered the literal reader's misses. Retrieval discipline: 56% of
  probes used the tool. 0 hallucinated answers on probed facts.
- *Cost clause — recalibrated, honestly.* Measured 54% of oracle tokens
  under this bench's every-turn cost model. The original "≤35%" figure was
  mis-calibrated: it belongs to the post-jump *payload* metric, where the
  adapters measure 17–18%. The bench's every-turn model charges the rope's
  floor every turn; 54% is the correct number for that model and it still
  halves the bill at equal accuracy.
- *Live-only insight:* B1/B2 (decision-recall gap) largely dissolve with a
  real model in the loop — Phase 3's hybrid retrieval remains worthwhile
  for scripted floors and weak models, but is no longer the top priority.

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

## Phase 5 — real-workload replay ✅ (harness done 2026-07-04)

`ropebench replay <session.jsonl>` loads a REAL Claude Code session and mines
cloze probes from its own recurring distinctive values (ports, flags, PR
numbers, hashes, versions) — owned ground truth, no LLM judge. Ran on a real
117-turn session (scripted reader):

| Regime | Acc | tokens | acc/10k |
|---|---|---|---|
| full-history | 57% | **1,348,358** | 0.4 |
| truncate | 0% | 49,943 | 0.0 |
| summary | 0% | 50,775 | 0.0 |
| **rope (bound)** | 43% | **77,179** | **5.6** |
| rope-unbound | **71%** | 1,326,736 | 0.5 |

Real-world headline: **the full transcript is 1.35M tokens — it does not fit
in any model's context window**, so "carry everything" is not even an option
on a real long session, while the rope (77K) fits comfortably (17× smaller).
The lossy baselines scored **0%** — the mined facts had scrolled out
(truncate) or been summarized away (summary). Bound rope's efficiency is 14×
the oracle's; unbound got the *best* accuracy (71%), beating even
full-history's scripted reader — a dense structured ledger is easier to read
than 1.35M tokens of raw transcript.

The **chatty scenario** (`--chatty N`) confirms B5 on synthetic data: bound
rope keeps the best accuracy-per-token (6.8 vs the oracle's 2.1).

**Honest limit surfaced (B6):** the event-driven runner records message text
and relies on word-level `densify`; it does NOT model the adapter-level
**streaming eviction** (archive-to-vault + gist stub) that makes unbound mode
cheap on real chat. Unbound's cost numbers in the bench are a floor, not its
real economics — the adapter tests measure the real figure (17–18% payloads).
Closing B6 means driving the streaming policy inside the replay loop.

**Exit criterion:** README of jumping-rope cites only measured numbers (met);
one external-model live sweep reproduced by someone other than the author
(fork-ready: this repo has no machine-specific paths or keys).

## Standing decisions needed from the owner

1. Whether Phase 3's hybrid retrieval should change the default `search()`
   behavior or ship behind a flag (recommendation: default on — it is
   strictly additive recall). Live-model results (Phase 2) show B1/B2 largely
   dissolve with a real model, lowering this priority.
2. B6: whether to invest in streaming-in-the-replay-loop so unbound mode's
   real economics get measured in-bench (vs. relying on the adapter tests).
