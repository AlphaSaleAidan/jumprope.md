# RopeBench

**Measure what your agent's memory strategy actually costs you — on your own
sessions, your own models, in one command.**

Long agent sessions overflow the context window, and every framework has a
policy for what to do about it. RopeBench measures those policies head-to-head
with the model held constant: same session, same probes, different memory
strategy. Every number below traces to a row in [CLAIMS.md](CLAIMS.md) with its
sample size and 95% CI; reproduce them with [REPRODUCE.md](REPRODUCE.md).

```bash
pip install -e ".[dev]"

# measure your own Claude Code session
jrope-bench convert my-session.jsonl bench.jsonl
jrope-bench run --transcript bench.jsonl --conditions rope,carry,summarize --out out/
cat out/report_card.md          # headline + paired CIs + verdicts
# out/report.json is what you post to prove a reproduction
```

The strategies compared (the "conditions"): **carry** (full history — the
oracle, and the cost worst case), **truncate** (drop oldest), **summarize**
(what most frameworks do by default), **rope** (a real
[Jumping Rope](https://github.com/AlphaSaleAidan/jumping-rope) session — the
reference implementation), and **rope-unbound / streaming**.

---

## Finding 1 (the lead): auto-summarization silently destroys OLD facts

Auto-summarization is the industry default. It is also the worst performer on
exactly the thing you ask about later. Scored by **fact age** (when a fact was
introduced), scripted reader, 5 seeds:

| fact age | n | summary recall | rope recall | difference | 95% CI |
|---|---|---|---|---|---|
| **early** (oldest) | 65 | 74% | 94% | **−20.0%** | [−32.3%, −7.7%] |
| **mid** | 70 | 61% | 91% | **−30.0%** | [−42.9%, −17.1%] |
| **late** (recent) | 15 | 100% | 100% | +0.0% | [0%, 0%] |

The damage is real and significant (both CIs clear zero) and it is
**concentrated in old facts** — recent facts are untouched. This is the effect
you feel when a long agent session "forgets" a decision from an hour ago: the
summary ate the specifics. Large effect, survives the sample size. `CLAIMS.md`
C1–C3.

## Finding 2: on a long-enough session there is no "carry everything"

A real 117-turn Claude Code session is **1.35M tokens** — it does not fit in
any model's context window. The rope carries the same session in **~75K tokens
(18× smaller)** and fits. Past a point, "carry everything" is not a baseline
you can lose to; it is not an option at all, and the only real competition is
summarize-vs-rope — which summarize loses (Finding 1). `CLAIMS.md` C10–C11.

## Finding 3: the quality claim, at exactly the strength the CI supports

Does the rope match carrying the full transcript on accuracy? **It depends on
who's reading**, and we report both honestly:

- **Literal reader (scripted, n=150):** rope **trails** full-history by 6.7%
  (95% CI [−10.7%, −2.7%] — significant). A keyword-matcher does not exploit
  the retrieval tool well. `CLAIMS.md` C6.
- **Real model (live, Haiku, n=90):** the rope still **trails** full-history,
  but only by 4.0% (95% CI [−8.9%, −1.1%]) — a real model narrows the gap a
  literal reader can't, from −6.7% to −4.0%. And it **beats summary by +22.2%**
  (CI [+11.1%, +31.1%]) at 60% of the oracle's tokens (efficiency 7.2 vs 4.5).
  `CLAIMS.md` C7.

The honest summary: the rope is **not quite as accurate as carrying the whole
transcript** — a few significant points below, even live — but it trades that
for huge cost savings, it crushes the summarization every framework ships, and
on a long-enough session the oracle it trails **does not fit in the window at
all** (Finding 2).

What is **not** claimed: the single-seed Opus "rope beats carry-all 96 vs 92"
result (n=26) is directional only — its CI is not established, so it is not a
headline. It is consistent with the long-context degradation literature, and a
multi-seed frontier run is required before it becomes a claim.

What **is** robust regardless: the rope beats summarize decisively (+22.7%,
CI [+14.7%, +30.7%], n=150) and truncate (+7.3%, CI [+0.7%, +14.7%]) while
spending far fewer tokens — the best accuracy-per-token of the field.

## Finding 4 (B6 closed): unbound mode's economics, modeled in-bench

Unbound mode's cost mechanism is **streaming eviction** — the transcript is
dropped as it's captured. Earlier this rested on adapter tests; it is now
modeled in the bench with the *real* `apply_streaming_policy` (no
reimplementation). Result: streaming cost is **~flat as the transcript gets
chattier** while full-history explodes. At 4× conversational padding, streaming
is **29% of full-history**; on a filler-free stream it *loses* (nothing to
evict) — reported honestly, not hidden. `CLAIMS.md` C8, `tests/test_b6.py`.

---

## How it works

Same seeded session stream through each condition; probes with **owned ground
truth** (planted values, or auto-mined distinctive tokens from a real
transcript) scored by exact match — **no LLM judge**. Conditions are compared
on the **same probes**, so differences get a **paired bootstrap 95% CI**
(`ropebench/stats.py`, 10k resamples, seeded); a claim is written as
*superiority* only when the CI clears zero, else as *parity* (which, at a
fraction of the tokens, is itself a win).

Two reader modes: **scripted** (deterministic, hermetic, free — measures
*information availability*) and **live** (any OpenAI-compatible model or CLI —
measures *information use*).

## Cost safety (paid runs)

Live sweeps refuse to start without `JROPE_BENCH_BUDGET_USD`, print a
token-based cost estimate first, abort if over budget, and cache every
`(model, payload)` response under `bench_cache/` so reruns and re-grading are
free. Test tiers are marker-gated: `default` (CI, hermetic), `local`, `api`.

## Run it

```bash
# hermetic, free — reproduces Findings 1, 3, 4
jrope-bench run --runs 5 --turns 80 --out results/hardened-scripted
pytest -q && ruff check . && mypy --strict ropebench

# your own model (paid — needs a budget)
export JROPE_BENCH_BUDGET_USD=5.00
jrope-bench run --runs 3 --mode live --model anthropic/claude-haiku-4-5 --out out/
```

Full reproduction commands: [REPRODUCE.md](REPRODUCE.md). Development plan and
open work: [ROADMAP.md](ROADMAP.md). The rope system is reference
implementation #1 among the conditions — RopeBench measures policies, and ships
one. MIT.
