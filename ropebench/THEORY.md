# The theory of Jumping Rope — and what the benchmark has proven

## The core claim (upgraded)

An agent's session state does not belong in the transcript. Externalize it into
a **dense, structured, budget-bounded ledger with a retrieval tier**, and you
get a system that:

1. **fits when the transcript doesn't** — the ledger is bounded; the transcript
   grows without limit and eventually exceeds every context window;
2. **costs far less** — and the saving *grows* with session length;
3. **beats the summarization every framework ships by default** — decisively,
   and specifically on the old facts summaries destroy;
4. at an honest, small accuracy cost vs the (often impossible) full-transcript
   oracle — a cost a capable model narrows and a tight budget offsets.

Every clause below is measured, with a 95% CI, reproducible from a fresh clone.

## Sub-theories tested (RopeBench research log)

| # | Hypothesis | Verdict | Key number |
|---|---|---|---|
| **T1** | The value of the memory hierarchy grows with session length | **CONFIRMED** | full-history O(n^1.34), rope O(n^0.73) → advantage O(n^0.61); 4.5× cheaper at 260 turns |
| **T2** | Density has a floor — past a point, compression hurts recall | **CONFIRMED** | ai-native §-coding drops literal-reader recall 93%→82% (codes away matchable context words) |
| **T3** | Structure beats a flat dense blob | **CONFIRMED** | structured rope 96% vs flat-dense 62% at long distance — a 34-pt gap, all in OLD facts |
| **T4** | Retrieval quality sets the optimal budget | **CONFIRMED (counterintuitive)** | efficiency maximized at the *tightest* satisfiable budget (25.3 @ 400 tok → 5.6 @ 3600); a smaller rope forces retrieval and the vault compensates |
| T5 | Recency / section ordering affects recall | *deferred (needs live)* | scripted literal reader is position-invariant; ordering is a live-model "lost in the middle" effect |
| T6 | Model capability × retrieval — stronger models exploit the vault more | *partially observed* | live Haiku narrows the literal reader's −6.7% gap to −4.0%; frontier tiers all show rope as best acc/token |
| **T7** | Exact addressing survives distractors that sink semantic search | **CONFIRMED** | flat semantic recall of a specific fact 100%→0% as near-duplicates grow (N=0→64); rope's turn-stamped KEYS exact-fetch stays 100%; AI-native coding makes semantic fail *faster* (48%→33% at N=4), widening the gap |
| **T8** | The rope is noise-robust; its margin over lossy baselines widens with filler | **CONFIRMED** | at 16× conversational filler, rope 44% vs truncate/summary 16%; rope−truncate margin 7pt→28pt as filler grows |

## What the confirmed sub-theories add up to

The four confirmed results are not independent surprises — they compose into a
single design principle: **push state out of the resident context as
aggressively as you can, and lean on structured retrieval.**

- T4 says the resident rope should be *small* (tight budgets win).
- T3 says what stays resident should be *structured* (sections + index), so the
  small resident set still finds old facts.
- T1 says this matters *more* the longer you run.
- T2 is the guardrail: compression that destroys matchable surface form
  (ai-native for a weak reader) crosses the floor — density serves retrieval,
  it does not replace it.
- T7 resolves the T2 tension and explains *why* T3 works: structure wins because
  it makes old facts **addressable**. An exact, content-addressed KEYS handle is
  immune to how crowded the store gets — where pure semantic search on
  near-duplicates collapses to chance. And because the handle is exact, the
  archive can be coded as aggressively as you like: AI-native densification is
  *safe on the retrieval tier* (it even widens the exact-vs-semantic gap), so
  T2's warning is confined to the resident rope a weak reader must scan.
- T8 is the stress test: as real sessions bury facts in conversational filler,
  the lossy strategies (truncate, summarize) collapse while the rope degrades
  gracefully — its margin *widens* with noise.

The oracle (carry everything) wins on raw accuracy by a few points — but it is
the one strategy that *cannot run* on a long session, and the strategy everyone
actually ships (summarize) loses to the rope badly. The rope is the strategy
that is both *possible* and *good*.
