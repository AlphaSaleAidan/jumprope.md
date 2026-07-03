# RopeBench

**Effectiveness benchmark for LLM context-handoff strategies.** Measures a
context-management *policy* with the model held constant — the inversion
normal benchmarks can't do.

[Jumping Rope](https://github.com/AlphaSaleAidan/jumping-rope) claims that a
token-dense rope file plus a vector overflow store preserves session state at
a fraction of the cost of replaying the transcript. RopeBench tests that
claim against the real alternatives, on the axes normal benchmarks don't
have.

## How this differs from normal benchmarks

| Normal benchmark | RopeBench |
|---|---|
| varies the model, fixes the context | fixes the model, varies the **context regime** |
| one-shot, stateless tasks | longitudinal: probes planted at distances measured in **turns and compactions survived** |
| scores answer accuracy | scores **state continuity**: fact retention by distance, decision recall, goal status, retrieval discipline |
| ignores cost | cost is a first-class axis: the output is a **Pareto row** (accuracy per 10k tokens) |
| absolute scores | deltas against matched baselines: full history (oracle), truncate-oldest, summary compaction |
| fixed answers or LLM judges | synthetic scenarios with **owned ground truth** — scoring is substring matching, no judge noise |

## The four regimes

Same seeded event stream (facts, decisions, goal transitions, filler churn),
four context policies:

1. **full-history** — carry everything; the oracle ceiling and the cost worst case
2. **truncate** — drop-oldest under a token budget
3. **summary** — deterministic stand-in for auto-compaction: old lines
   collapse to their first words, then drop (loses trailing detail, exactly
   like real summarization)
4. **rope** — a real `JumpingRopeSession`: hard-budget rope + TurboVec
   retrieval tool

Two modes:

- **scripted** (CI, zero network): a deterministic literal reader answers
  probes from whatever the regime shows it — measures **information
  availability**, the necessary condition.
- **live**: any OpenAI-compatible model answers instead — measures
  **information use** (including hallucinated continuity and whether the
  model actually issues `RETRIEVE:` on cache misses).

## Measured results (scripted mode, 3 seeds × 80 turns, 78 probes)

| Regime | Acc | short | medium | long | fact | decision | status | retrieval | tokens | acc/10k tok |
|---|---|---|---|---|---|---|---|---|---|---|
| full-history | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 0% | 280,455 | 3.6 |
| truncate | 91% | 100% | 100% | 67% | 92% | 88% | 94% | 0% | 201,517 | 4.5 |
| summary | 79% | 100% | 100% | 24% | 75% | 75% | 94% | 0% | 192,357 | 4.1 |
| **rope (bound)** | **95%** | 100% | 87% | **100%** | 100% | 83% | 100% | 51% | **148,607** | **6.4** |
| rope-unbound | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 0% | 498,828 | 2.0 |

The story: at long distance — the regime a context strategy exists for —
bound rope holds **100%** while truncation falls to 67% and summary
compaction to 24%, at ~half the oracle's token spend and the best
accuracy-per-token of the field. **Unbound rope matches the oracle on every
cell** (perfect verbatim recall, zero retrievals) — and the honest cost
number is that on this *pre-distilled* event stream it costs MORE than the
oracle (per-record structure + legend overhead; every decision line carries
a full ISO date). Unbound's economics win against real chat transcripts —
17–18% payloads measured in the adapter tests — which this event-driven
scenario does not model. Findings B1–B5 in `ROADMAP.md`.

## Run it

```bash
pip install -e ".[dev]"          # pulls jumping-rope from its repo
pytest -q                        # 25 tests, zero network

# deterministic sweep (CI mode)
ropebench run --mode scripted --seeds 3 --turns 80 --out results/

# live sweep against any OpenAI-compatible endpoint
ropebench run --mode live --seeds 3 \
  --base-url https://openrouter.ai/api/v1 --model deepseek/deepseek-chat \
  --api-key $KEY --out results/live/
```

`results/report.md` gets the table, `results/results.csv` the per-probe rows
(regime, tag, kind, distance bucket, hit, retrieval-used, answer).

## Extending

- New regime: subclass `RegimeBase` (`observe` / `context` / `retriever`).
- New probe kinds: extend `scenario.generate` — probes carry
  `expected_any` alternatives so regimes with different surface forms
  (glyphs vs prose) score fairly.
- The regression gate for jumping-rope development is
  `tests/test_e2e.py::test_regime_ordering_claims`.

MIT. Development plan in [ROADMAP.md](ROADMAP.md).
