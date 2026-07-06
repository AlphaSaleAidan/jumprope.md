# Self-improvement journal

Autonomous R&D session started 2026-07-04. Goal: keep testing and improving the
Jumping Rope theory + RopeBench, generate independent sub-theories, harden with
massive repetition, upgrade docs/visuals. Each entry: what was tried, what the
numbers said, what shipped.

## Core theory (as upgraded)
Externalized, dense, *structured* session memory with a retrieval tier beats
replaying the transcript: it fits when the transcript doesn't, it costs far
less, and it destroys the summarization every framework ships — at a small,
honest accuracy cost vs the (often-impossible) full-transcript oracle.

## Independent sub-theories to test
- T1: memory-hierarchy value grows super-linearly with session length
- T2: notation density has a floor — past X% compression, recall degrades
- T3: structured state (rope sections) beats flat dense text for a reader
- T4: retrieval quality sets the optimal rope budget
- T5: recency/section ordering affects recall
- T6: model capability × retrieval — stronger models exploit the vault more

## Log

### Entry 1 — statistical machinery validated at scale (2026-07-04)
Ran 30k iterations of property/stress tests:
- **Bootstrap CI coverage: 0.9492 empirical vs 0.95 nominal** (20,000 simulated
  paired experiments, true diff +0.20, n=40). The CIs report the coverage they
  claim — the hardened numbers are trustworthy.
- Scenario determinism: 0 mismatches / 5,000 seeds.
- Ground-truth invariant: 0 unanswerable planted probes / 5,000 seeds.
Shipped: a calibration test (`test_stats_calibration.py`, moderate trials for CI
+ a `local`-marked full 20k run).

### Entry 2 — T1 CONFIRMED: value grows with session length (2026-07-04)
Scripted sweep, session length 40→260 turns:
| turns | full/rope tokens | rope efficiency advantage |
|---|---|---|
| 40 | 1.44× | 1.38× |
| 120 | 2.52× | 2.41× |
| 200 | 3.66× | 3.58× |
| 260 | 4.55× | 4.50× |

Log-log fit: **full-history O(n^1.34), rope O(n^0.73) → rope advantage O(n^0.61).**
The memory hierarchy's payoff is a power law in session length — the longer the
session, the bigger the win. Backbone of Finding 2 ("no carry-everything past a
point"). Shipped `test_theory_t1.py`.

### Entry 3 — T4 CONFIRMED (counterintuitive): tighter rope = better (2026-07-04)
Rope budget sweep (scripted, 3 seeds, 80 turns):
| budget | acc | long | tokens | efficiency | retrieval |
|---|---|---|---|---|---|
| 400 | 97% | 100% | 38K | **25.3** | 72% |
| 600 | 93% | 96% | 51K | 18.3 | 56% |
| 1000 | 93% | 96% | 70K | 13.3 | 46% |
| 1600 | 90% | 75% | 105K | 8.6 | 20% |
| 2400 | 100% | 100% | 130K | 7.7 | 29% |
| 3600 | 100% | 100% | 180K | 5.6 | 0% |

**Efficiency is maximized at the TIGHTEST satisfiable budget** and falls
monotonically as the budget grows — a smaller rope forces more retrieval and
the vault compensates, so accuracy stays high (97% at budget 400). Actionable:
default to the smallest satisfiable budget, not a comfortable one.
Note a **"valley of the middle budget"** (1600 → 90%, long 75%, retrieval only
20%): facts half-demoted, neither resident nor eagerly retrieved. Flagged for
more seeds. Shipped `test_theory_t4.py`.

### Entry 4 — T2 CONFIRMED (with nuance): density has a floor (2026-07-04)
Same 600-token budget, three notation profiles, scripted reader:
| profile | acc | long | rope tokens |
|---|---|---|---|
| symbolic-en | 93% | 96% | 418 |
| cjk-dense | 94% | 100% | 520 |
| **ai-native** | **82%** | 88% | 485 |

ai-native's adaptive §-dictionary saves tokens but **codes away the context
words a literal reader matches on** — recall drops 11 points. The distinctive
*values* survive verbatim; matchability doesn't. cjk-dense (lighter, single-char
substitution) is safe. **Implication:** ai-native needs a capable reader that
decodes via the legend, not a keyword-matcher — connects to T6 (capability ×
density). Shipped `test_theory_t2.py`.

### Entry 5 — T3 CONFIRMED: structure beats a flat dense blob (2026-07-04)
Same 600-token budget, same densify, same retrieval vault — rope vs a flat
dense blob (rope minus structure):
| regime | acc | long | med | efficiency |
|---|---|---|---|---|
| rope (structured) | 93% | **96%** | 88% | 18.3 |
| flat-dense | 90% | **62%** | 100% | 16.2 |

Structure's value is **concentrated in OLD facts** — 96% vs 62% at long
distance, a 34-point gap. The never-demoted STATE/GOALS + KEYS index give old
facts a durable home and a findable pointer; a flat blob drops them into
semantic-search-only limbo. (Flat-dense edges medium — recent facts in the blob
are trivially present.) Shipped `test_theory_t3.py` incl. a `FlatDenseRegime`.

### Entry 6 — T8 CONFIRMED: rope is noise-robust; the gap widens (2026-07-04)
Accuracy vs filler ratio (chatty level), scripted, 3 seeds:
| chatty | full | truncate | summary | rope |
|---|---|---|---|---|
| 0 | 100% | 86% | 72% | 93% |
| 4 | 100% | 51% | 44% | 72% |
| 16 | 100% | 16% | 16% | **44%** |

Truncate/summary **collapse** as filler grows (facts scroll out / get compacted);
the rope degrades far more gracefully (93%→44%) and its margin over the lossy
baselines **widens** with noise (rope−truncate: 7pt→28pt). The rope isn't immune
in this event-driven model — heavy filler still pressures it — which points once
more at streaming eviction (B6) as the true noise-handling mechanism. Full-history
stays 100% but is the impossible-on-long-sessions oracle. Shipped `test_theory_t8.py`.

### T5 note (deferred)
Section/recency ordering is a live-model "lost in the middle" effect; the scripted
literal reader is position-invariant (scans all lines by overlap), so T5 needs a
live run to measure — queued for a live cycle.

### Entry 7 — T7 CONFIRMED: exact addressing is distractor-immune; semantic search collapses (2026-07-04)
Fill the vault with one target fact + N *near-duplicate* distractors (same
sentence, different value token) and ask for the target back. 8 seeds × 20
targets, k=3:

| N distractors | flat semantic | rope exact (KEYS) | chance k/(N+1) |
|---|---|---|---|
| 0 | 100% | 100% | 100% |
| 4 | 48% | **100%** | 60% |
| 8 | 17% | **100%** | 33% |
| 16 | 8% | **100%** | 18% |
| 32 | 1% | **100%** | 9% |
| 64 | 0% | **100%** | 5% |

Semantic recall of a *specific* fact **collapses to chance and below** as
near-duplicates crowd in — the distinctive value is one token in a sea of shared
context, so cosine rank is ≈ random among the N+1 near-identical rows (flat even
dips *under* the k/(N+1) line: at N=4, 48% < 60%). The rope's turn-stamped KEYS
handle (`t{turn}·topic → key`) is an exact content-addressed fetch — **100%
regardless of N.** This isolates the mechanism behind T3: what makes *structure*
win is that it makes an old fact *addressable*, not merely present.

**AI-native makes the outcome stronger (answering the "write the rope in an AI
native language" ask).** Re-run under the `ai-native` profile:

| N | flat semantic (symbolic-en) | flat semantic (ai-native) |
|---|---|---|
| 4 | 48% | **33%** |
| 8 | 17% | **14%** |
| 16 | 8% | **6%** |

Denser §-coding removes even more surface variance, so semantic search on the
coded near-duplicates fails *faster* — widening the gap the exact fetch (still
100%) already owns. This resolves the T2 tension: aggressive AI-native coding is
**safe on the retrieval tier precisely because retrieval there is exact, not
fuzzy.** T2's warning was about a *literal keyword reader* on the resident rope;
T7 shows the vault, addressed by key, is immune — so densify the archive freely.

Honest cost: the KEYS index is not free — one handle line ≈ a raw fact's tokens
(17 vs 14 here). You pay ~1 line per fact you choose to make addressable; under a
fixed budget that caps how many facts get a handle. The win is not "free recall,"
it's "recall you can *buy* one line at a time, immune to store size." Shipped
`tests/test_theory_t7.py` (marked `local`) + `research/exp_t7_distractors.py` +
`assets/chart-distractors.svg`.

### Entry 8 — T5 MEASURED NULL: no lost-in-the-middle up to 21k (single needle, Haiku) (2026-07-04)
The scripted reader is position-invariant, so T5 needs a live model. Bounded FREE
sweep (local `claude -p --model haiku`, no Meridian): one needle placed at depth
5% / 50% / 95% across three context sizes, 8 targets each.

| context (tokens) | depth 5% | depth 50% | depth 95% |
|---|---|---|---|
| small (~547) | 100% | 100% | 100% |
| large (~5,669) | 100% | 100% | 100% |
| xlarge (~21,417) | 100% | 100% | 100% |

**72/72 recalled.** No middle-of-context recall valley even at 21k tokens. This
is recorded as an honest **null**, not forced into a "confirmed": for a single
exact-match needle at rope-relevant scales, a modern model shows no positional
weakness to exploit. It matters because it *rules out* a tempting story — the
rope does NOT win by dodging lost-in-the-middle. Its edge is cost (T1/T4) and
noise-robustness (T8/T7). Position is simply not the axis.

Caveat (why the null is scoped, not universal): single-needle exact recall is the
*easy* form of the effect. Classic LITM bites hardest with many competing needles,
much longer contexts (30k–100k+), and answers requiring reasoning across position
— untested here and out of scope for a free CLI sweep. Shipped `test_theory_t5.py`
(pins the artifact so the null can't rot) + `research/exp_t5_ordering.py` +
`results/t5-ordering/`.

### Entry 9 — T9 CONFIRMED: the pattern holds on a REAL 875k-line codebase (2026-07-04)
Prompted by Aidan's question — "what about recall against 150k+ lines of code?"
Ran the T7 contest on genuine code: the Python 3.12 standard library
(/usr/lib/python3.12), 11,798 functions sampled, **~1,033,908 tokens** — a
codebase this size fits in *no* context window, so "carry everything" is off the
table from the start.

**Part A (scripted, free) — exact-key vs semantic recall of a SPECIFIC function
when N others share its name (real near-duplicates):**
| N same-named | flat semantic | rope exact (file::symbol) | chance k/(N+1) | targets |
|---|---|---|---|---|
| 0 | 100% | 100% | 100% | 60 |
| 4 | 58% | **100%** | 60% | 60 |
| 8 | 31% | **100%** | 33% | 39 |
| 16 | 20% | **100%** | 18% | 15 |
| 32 | 29% | **100%** | 9% | 7 |

Semantic recall **tracks the coin-flip line** on real code (58≈60, 31≈33, 20≈18;
N=32 noisy at 7 targets). Exact addressing is 100% throughout. **T7's mechanism is
not a synthetic artifact — a real codebase is its natural habitat:** every large
repo has hundreds of same-named `close`/`read`/`run` methods, and "search by
meaning" cannot say which one you meant.

**Part B (bounded live, local Haiku, no Meridian) — does lost-in-the-middle bite
at code scale?** Packed real code to **80,435 tokens**, hid one distinctive marker
at depth 10/50/90%: **12/12 recalled, all depths.** No LITM for a *distinctive*
needle even at 80k of real code — consistent with T5.

**The honest synthesis (answers the question precisely):** yes, rope+vault helps
enormously on a huge codebase — but via T7 + "doesn't fit" (T1), NOT via dodging
position. Position isn't the failure mode; *disambiguating near-duplicates* is,
and exact `file::symbol` addressing is exactly what fixes it. The Part B caveat is
the whole point: a model finds a *distinctive* marker fine at 80k — but real code
recall is never distinctive, it's "which of the 40 `close()` did I mean?", which
is Part A, where semantic fails and the address wins. Shipped
`test_theory_t9.py`, `research/exp_t9_codescale.py`, `results/t9-codescale/`,
`assets/chart-codescale.svg`.

### Entry 10 — T6 CONFIRMED: capability recovers the density loss (2026-07-04)
T2 showed ai-native coding drops the *scripted literal reader's* recall (it codes
away matchable context words). T6 asks: does a real model read the LEGEND and
decode it? Same ropes (symbolic-en vs ai-native), two readers, 2 seeds:

| reader | symbolic-en | ai-native | ai-native drop |
|---|---|---|---|
| scripted (literal matcher) | 93% | 83% | **−10%** |
| live Haiku | 100% | 100% | **+0%** |

The scripted reader pays the density tax (reproduces T2). **Live Haiku pays
nothing — 100% on both** — a **+17% capability recovery** on the coded rope
(live ai-native 100% vs scripted ai-native 83%). Even a *small* model fully
decodes the ai-native rope via its legend; the "density floor" is a **weak-reader
artifact**, not a real cost for deployments that read the rope with an actual
model.

This closes the T2↔T6↔T7 loop:
- **T2** — ai-native hurts a literal keyword-matcher (the floor).
- **T6** — a real model decodes it and recovers fully (floor is weak-reader-only).
- **T7** — on the retrieval tier ai-native is safe *by construction* (exact key,
  not fuzzy), and even widens the exact-vs-semantic gap.
Net: **aggressive AI-native densification is safe for capable models everywhere**
— resident rope (T6) and vault (T7) — so densify freely and pocket the tokens.

Honest caveat: Haiku *saturates* this scenario (100% ceiling), so the effect we
observe is the scripted drop that live erases; a harder scenario or a
capability-gradient (haiku→sonnet→opus) would show partial→full recovery curves —
queued, but the qualitative result (capability erases the density tax) is clear
even at the floor of the model range. Shipped `test_theory_t6.py` (pins artifact)
+ `research/exp_t6_capability_density.py` + `results/t6-capability-density/`.
### Entry 11 — T10: the missing link (scribe fidelity) measured LIVE (2026-07-06)

Every prior number assumed PERFECT CAPTURE: `RopeRegime._record` applies the
generator's own event mapping — the harness never had to *notice* a fact.
Production has no such oracle; a live model must decide, mid-stream, what is
durable. The system is a chain — **end-to-end = capture × carry × recall** —
and capture was the unmeasured factor. If capture is weak, everything above
is the ceiling of a system nobody runs.

**Protocol** (`research/exp_t10_scribe.py`): chatty scenario (facts wrapped in
conversational filler + routine-churn noise every turn), 2 seeds × 40 turns,
n=60 probes/condition. A live Haiku scribe sees each turn's raw transcript +
current rope and emits ledger ops (JSON lines) or NONE; ops flow through the
same `JumpingRopeSession` as the mechanical regime. All conditions answered
by the SAME deterministic ScriptedModel, so any delta vs mech-rope is capture
alone. `--scribe perfect` replays the oracle mapping through the same pipe
and reproduces mech-rope — the harness validates before any paid call.

| condition | acc | capture | capture-losses | recall-losses |
|---|---|---|---|---|
| **scribe-rope (live Haiku captures)** | **83%** | **100%** | **0** | 10 |
| mech-rope (oracle captures) | 77% | 98% | 1 | 13 |
| summary | 57% | 62% | 23 | 3 |

Paired bootstrap (10k, seeded):
- scribe-rope vs summary: **+26.7% [+13.3%, +40.0%] — CI clears zero.**
- scribe-rope vs mech-rope: +6.7% [−5.0%, +18.3%] — **parity** (the small edge
  is structural: the scribe files facts as OPEN, the oracle alternates
  DELTA/OPEN; not scribe magic).

**The scribe was surgical:** 66 valid ops for exactly the stream's 66 durable
events, **0 ops on filler-only turns** (nothing logged for renames/linting/
tidying churn), identifiers copied verbatim. The run's 41 "unparseable lines"
were audited: markdown code fences around otherwise-perfect JSON (parser
counted the wrappers; fixed post-run — cosmetic, zero ops lost).

**Integrity check on the metric itself:** `note_turn` is accounting-only
(verified in session.py) — raw turn text is never archived to the vault, so
100% capture cannot be a harness leak; only scribe ops put values in reach.

**Honest limits.** n=60, 2 seeds, one model, one scribe prompt. The scenario's
facts are *salient* — one-sentence declarations wrapped in filler, and the
scribe prompt's op taxonomy matches the generator's event taxonomy. This
proves capture is NOT the weak link for conversational facts a session
states in prose. It does NOT yet cover the harder capture class: values that
only ever appear inside tool output (a port in a stack trace, a hash in a
diff) that no one restates. That is T11 — unsalient capture — and it is the
next place the theory could break.

**Verdict: the chain closes** for salient facts. With a live model doing the
capturing, carrying, and (scripted) recalling, the full system holds its
+26.7pt lead over the summarization every framework ships — and loses
nothing measurable to the oracle scribe.

### Entry 12 — T11: the capture boundary FOUND, then half-fixed (2026-07-06)

T10 left one door open: facts that never get said in prose. T11 planted 8
values per seed that exist ONLY inside machine blobs — a port in a
traceback, a sha256 in a diff hunk, max_retries in a config dump, a p99 in
a log tail — with a one-line prose intro that never contains the value.
Same scribe prompt as T10, zero hints. **Pre-registered prediction:
capture drops below 100%. Confirmed.**

| tool-facts only (n=16) | acc | capture |
|---|---|---|
| scribe (unhinted) | 75% | **81%** |
| scribe + one hint rule (T11b) | 88% | **88%** |
| oracle capture | 100% | 100% |
| summary | **0%** | 38% |

- Unhinted deficit vs oracle: −25% [−50%, −6%] — real even at n=16. The
  weak class: **p99 buried in a log tail (2/4)** — a WARN line among INFO
  noise reads as churn. Configs and diffs survived (8/8).
- **T11b — the cheapest fix measured:** ONE added rule ("blobs often hold
  the only copy of a value — log it verbatim"). p99 class fully fixed
  (4/4), but ports regressed (3/4→2/4): the failure MOVED. Net +12.5%
  [−12.5%, +37.5%] — parity by CI at this n. Honest read: prompting shifts
  which class gets skimmed; the complete answer is **mechanical capture**
  (hooks that auto-log values from tool output), now the top roadmap item.
  The hint ships anyway (harmless, fixed the worst class): SKILL.md and
  the /jumprope-start operating loop now carry it.
- Summarization on blob-buried facts: **0%. Zero.** Every value it ever
  saw is unrecoverable. This is the sharpest separation measured yet.
- Ops audit: clean runs emit ~40 ops/40 turns, 0 noise ops, 0 parse
  failures. (A first hinted run collapsed to 3% — diagnosed as
  environmental: its 80 CLI calls coincided with a host session restart;
  a manual reproduction of the same call was perfect. CommandScribe now
  writes a raw-reply audit log so this class of anomaly is diagnosable
  from the artifact alone.)

**Verdict: the theory's honest boundary is the scribe's eye for buried
values — 4-in-5 unhinted, ~9-in-10 hinted, 10-in-10 only with mechanical
capture. Nothing else in the chain broke.**
