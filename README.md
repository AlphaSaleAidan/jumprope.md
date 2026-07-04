# jumprope.md

[![ci](https://github.com/AlphaSaleAidan/jumprope.md/actions/workflows/ci.yml/badge.svg)](https://github.com/AlphaSaleAidan/jumprope.md/actions/workflows/ci.yml)

<p align="center"><img src="assets/hero.png" width="880" alt="Jumping Rope — a session carries a dense rope of memory, leaping over the cleared transcript"></p>

**Long AI sessions forget things and get expensive. Jumping Rope fixes both
by keeping the session's memory in a small ledger instead of the chat
history.**

The color code used in every diagram below: **yellow** = the chat history,
**blue** = the rope (the ledger), **purple** = the vault (deep storage),
**green** = the model.

---

## 1. The idea in one picture

<p align="center"><img src="assets/overview.svg" width="920" alt="overview diagram"></p>

**How to read it.** Follow the arrows left to right. As the conversation
runs, everything that actually matters — a fact, a decision, a goal, an
unresolved problem — is copied onto the rope in a compressed notation
(solid thin arrow). The rope is the only thing the model has to carry
between turns (thick arrow). If the rope ever sheds older detail, that
detail moves *down* into the vault in full, never deleted (solid thin
arrow), and the model can pull it back with a lookup (dotted arrow). The
chat history itself is now disposable: clearing it loses nothing, because
nothing lives only there.

---

## 2. Two modes — pick per session

| | **BOUND** | **UNBOUND** |
|---|---|---|
| The rope | hard cap: 2,000 tokens | grows as needed (still tiny vs. chat) |
| What gets deleted | oldest rope detail — moved to the vault | the chat history itself, as soon as it's saved |
| When context clears | every ~8 turns, all at once ("the jump") | continuously, every single turn |
| Where old details live | the vault (one lookup away) | still on the rope, word-for-word |
| Main risk | a lookup can miss (measured below) | rope size on week-long sessions |

**Use BOUND when** the agent runs unattended for days and token cost
dominates; the model's context window is small or expensive; you're
metering an API middleware where every token is billed; or the session is
full of churn nobody will ever ask about again.

**Use UNBOUND when** the work is interactive and a failed lookup would
stall you — decisions and facts stay on the rope verbatim, so there is no
recall risk at all; the model has a large, cheap context window; sessions
run hours to days; or you want the rope's key section to double as a
turn-by-turn index of the conversation (each saved message gets a
`t42·`-stamped entry — "saved at turn 42").

Switching is one flag: `jrope init --mode unbound`, `JumpConfig.unbound()`
in Python, the `MODE` valve in Open WebUI, `JROPE_MODE` for the proxy.

**Stack them.** The modes compose as lifecycle phases: work **unbound**
while a session is hot (zero recall risk), then run `jrope retire
--budget 2000` when it goes cold — one explicit pass that vaults everything
over budget and leaves the compact bound artifact. Deliberately never
automatic: surprise mid-flow compaction is the failure mode unbound exists
to avoid.

---

## Which feature, when

| Feature | Reach for it when |
|---|---|
| **BOUND mode** | unattended agents running days, small/expensive context windows, billed middleware, churn-heavy sessions |
| **UNBOUND mode** | interactive work where a missed lookup stalls you; big cheap context windows; hours-to-days sessions |
| **`retire`** | a hot unbound session goes cold: end of day, project handoff — compact it to a ~2k artifact, everything else vaulted |
| **`symbolic-en` notation** | the default — 42% fewer tokens than prose, always on |
| **`ai-native` notation** | long repetitive sessions (agents doing similar operations all day) — learns the session's own phrases, another ~17% off |
| **The vault + `jrope query`** | any "what was that detail from earlier?" moment — exact-key or semantic lookup instead of scrolling |
| **Turn provenance (`t42·` stamps)** | auditing: every vaulted item's K-line tells you which conversation turn produced it |
| **Claude Code skill** | long coding sessions in Claude Code — maintains ROPE.md automatically, re-seeds after compaction |
| **Open WebUI pipe** | self-hosted chat UIs — paste one file, get streaming eviction per conversation |
| **OpenAI-compatible proxy** | any existing stack (middleware): point the client at the proxy, sessions get ropes transparently |

---

## 3. What the rope actually looks like

```markdown
# ROPE v1 | sess:a1b2c3 | j:2 | t:2026-07-04T09:00:00Z
## STATE
branch:feat/rate-limiter
## GOALS
✓ G1|impl token-bucket limiter
▶ G2|wire limiter into middleware
## DECISIONS
D4|2026-07-03|redis INCR over lua script|simpler, atomic enough
## OPEN
O2|P1|EXPIRE race under concurrent INCR
## KEYS
K7|t34·user: original perf reqs|tv-8a0b8122
```

**How to read it.** Line by line: the header says this is session `a1b2c3`,
the context has been cleared twice (`j:2`). `STATE` holds always-true facts
(current branch). `GOALS` uses one status mark per goal — `✓` done, `▶`
active, `◌` waiting, `✗` failed. `DECISIONS` records *what* was decided and
*why*, because the "why" is the first thing a summary loses. `OPEN` is the
unresolved-problems list with priorities (`P1` = important, survives
everything). `KEYS` is the index into the vault: entry `K7` says "the full
text of the user's message from turn 34 is in the vault under key
`tv-8a0b8122`". The whole file reads telegram-style on purpose — measured
**42% fewer tokens than plain prose**, and the `ai-native` profile saves a
further **17%** on repetitive sessions by abbreviating the session's own
recurring phrases (each abbreviation declared once in a legend).

---

## 4. How the machinery works

### What happens when the rope is full (BOUND mode)

<p align="center"><img src="assets/compactor.svg" width="920" alt="compactor diagram"></p>

**How to read it.** Every write lands on the rope first. If that pushes the
rope over its 2,000-token cap, the compactor evicts — but never blindly:
the top box (state, goals, legend) is untouchable; eviction takes the
*oldest* decision or file-change first, and only low-priority open items,
never urgent ones. Each evicted row goes to the vault **in full** and
leaves a one-line index entry behind (bottom box) so it can always be found
again. If even the index grows too long, old index rows are bundled into a
single summary row whose label lists a keyword from every bundled item —
that keyword list is what lets a brand-new session navigate down to any
buried fact. This exact path was attack-tested: a simulated "cold reader"
recovered 20 of 20 planted facts through it.

### What a context clear looks like (the jump)

<p align="center"><img src="assets/jump.svg" width="920" alt="jump diagram"></p>

**How to read it.** Three panels, left to right in time. **Panel 1 —
during work:** every meaningful change in the chat is copied down onto the
rope, compressed. **Panel 2 — the jump:** the chat history is erased (the
crossed-out card); the rope survives untouched — and because everything
important was already on it, nothing is actually lost. **Panel 3 — the
fresh session:** the model resumes from the rope alone, and when it needs
an old detail the rope doesn't carry, it fetches the original text from the
vault by key — a lookup, not a guess. In UNBOUND mode there is no discrete
jump: panel 2 happens continuously, one message at a time, the moment each
message has been saved.

---

## 5. Does it actually work? (measured, not vibes)

Method: the same scripted 80-turn session is replayed through five memory
strategies. Questions about planted facts are asked throughout, and each
strategy is scored on what it can still answer and what it spent. Full
methodology and code: [`ropebench/`](ropebench/).

The five strategies, in the order they appear in every chart:

1. **carry everything** — never delete anything (perfect memory, maximum cost)
2. **cut oldest** — when full, delete the oldest messages
3. **auto-summarize** — when full, compress old messages into summaries
   (what most AI tools do today)
4. **ROPE bound** — this project, BOUND mode (2,000-token ledger + vault)
5. **ROPE unbound** — this project, UNBOUND mode (ledger grows freely,
   nothing ever leaves it)

### Chart 1 — memory of old facts

<p align="center"><img src="assets/chart-memory.svg" width="920" alt="chart-memory diagram"></p>

**How to read it.** Each bar is one strategy; the height is the share of
40-plus-turn-old facts it could still answer. Carrying everything scores
100% by definition — that's the ceiling, not a competitor. Cutting the
oldest messages forgets a third. Auto-summarize is the striking one: it
forgets **three out of four** old facts, because summaries eat exactly the
things you ask about later — exact values, reasons, details. Both rope
modes match the ceiling: bound gets there with its vault lookups (used on
half the questions), unbound trivially — nothing ever left its ledger.

### Chart 2 — cost of the identical session

<p align="center"><img src="assets/chart-cost.svg" width="920" alt="chart-cost diagram"></p>

**How to read it.** Same five strategies, now showing the total token bill
for the identical 80-turn session (every turn pays for whatever context
that strategy carries). Carrying everything costs 280k and grows
quadratically with session length. The lossy strategies save some cost
but, per Chart 1, pay for it in memory. **Bound rope is the cheapest of
all five at 149k — about half the ceiling** — because its carried context
is a capped dense ledger. The green bar is the honest one: **unbound rope
costs 499k here**, because this benchmark feeds pre-distilled events — a
stream with no filler for unbound mode to delete. Its economics win
against real chat transcripts (measured separately: post-clear payloads of
17–18%), and this gap is filed as benchmark work B5.

### Chart 3 — the bottom line (memory per token spent)

<p align="center"><img src="assets/chart-efficiency.svg" width="920" alt="chart-efficiency diagram"></p>

**How to read it.** This chart divides Chart 1 by Chart 2: how much correct
memory does each dollar of tokens buy? It's the single number that captures
the trade-off — a strategy could cheat Chart 1 by hoarding everything, or
cheat Chart 2 by deleting everything, but not this one. **Bound rope
delivers 6.4 accuracy points per 10k tokens — 1.8× better than carrying
everything** (3.6) and well ahead of both lossy baselines. Unbound rope
scores 2.0 on this stream for the reason Chart 2 explains: it buys perfect
verbatim recall, and on a pre-distilled stream that premium shows. Pick by
Chart 3 when cost rules; pick unbound when a single missed lookup costs
more than tokens do.

### Predictions vs. measurements

| Hypothesis (stated before measuring) | Predicted | Measured | |
|---|---|---|---|
| Dense notation saves tokens | ≥40% vs prose | 42.1% | pass |
| Post-clear payload is small | <20% of full history | 17–18% | pass |
| Beats lossy baselines on old facts, cheaper than the ceiling | — | 100% vs 67/24, at 53% cost (bound) | pass |
| A cold session can recover vaulted facts through the index | ≥19/20 | 20/20 | pass |
| A live LLM keeps ≥90% of its ceiling accuracy on the rope | ≥90% | **100% — equals the ceiling** (Haiku, 3 seeds × 80 turns), at 54% of its tokens, 0 hallucinated answers | pass |

The last row is the live-model run (Haiku 4.5, 390 probe calls): the model
on the bound rope was **indistinguishable from the same model carrying the
full transcript** — and it beat the deterministic reader, because a real
model composes better vault queries than literal keyword matching. It used
the retrieval tool on 56% of questions. One honest recalibration: the
original cost target ("≤35%") belongs to post-clear *payload* size (the
adapters measure 17–18% there); under this benchmark's pay-every-turn cost
model the correct number is **54% of the oracle's bill at equal accuracy**.
The lossy baselines got *worse* live: auto-summarize fell to 14% on old
facts — a real model cannot reconstruct what summaries destroyed.

---

## Frontier models & real sessions

Two follow-up runs that raise the bar past the synthetic sweep.

**It works across model tiers.** The same benchmark on Haiku 4.5, Sonnet 4.6
and Opus 4.8 — bound rope has the best accuracy-per-token on all three:

<p align="center"><img src="assets/chart-frontier.svg" width="920" alt="frontier comparison chart"></p>

**How to read it.** Two bars per model: grey is carry-everything, blue is the
rope, height is correct answers per 10,000 tokens (higher = more memory per
dollar). The rope wins on every tier. The strongest result is Opus, where the
rope also *beat carry-everything on raw accuracy* (96% vs 92%): a capable model
reasons better over a small focused ledger than over a noisy full transcript,
so here compression is not a trade-off — it is an improvement.

**It survives a real Claude Code session.** We replayed an actual 117-turn
session (`ropebench replay`, questions auto-mined from the session's own
distinctive values). The decisive number: the full transcript is **1.35M
tokens — it does not fit in any model's context window**, while the rope carries
the same session in **~75K (18× smaller)** and fits comfortably. A live model
fed the 1.35M-token transcript actually scored *worse* (43%) than the same model
on the rope — past a point, more raw context hurts. "Carry everything" is not
just expensive on a real long session; it is impossible.

---

## Bonus finding: the longer the session, the more the rope wins

<p align="center"><img src="assets/chart-scaling.svg" width="900" alt="token cost vs session length — carry-everything explodes, the rope stays flat"></p>

An autonomous research loop is testing independent predictions of the theory.
The first: **the memory hierarchy's payoff grows with session length**.
Carry-everything's cost grows O(n¹·³⁴) (every turn pays for all prior turns);
the rope's grows O(n⁰·⁷³). By 260 turns the rope is **4.5× cheaper**. Four more
confirmed sub-theories (density has a floor, structure beats a flat blob, tighter
budgets win, and the rope is noise-robust) are in `ropebench/THEORY.md`.

<p align="center"><img src="assets/chart-noise.svg" width="900" alt="accuracy vs conversational filler — the rope degrades gracefully while truncate and summarize collapse"></p>

The chattier the session, the more the rope pulls ahead: at 16× filler it holds
44% while truncate and summarize collapse to 16% — the rope's margin over the
strategies frameworks actually ship *widens* with real-world noise.

---

## 6. How it was hardened

1. **52 mechanics tests** — the token cap is re-checked after every single
   one of 200 writes; a 30-turn "money test" reconstructs a session from
   the rope alone and recovers every vaulted fact.
2. **29 adversarial tests, written to break it — and they did.** 8 real
   breaks found, fixed, and regression-locked: crash-timing that lost data,
   text injection that corrupted the ledger, a vault index that was
   silently useless to fresh sessions. Full report with all verdicts:
   [`jumping-rope/ADVERSARIAL_REPORT.md`](jumping-rope/ADVERSARIAL_REPORT.md).
3. **The benchmark of section 5**, re-run as a regression gate on every
   change since.

All 116 tests are deterministic and run with zero network access.

---

## 7. Components

| Dir | What | Status |
|---|---|---|
| [`jumping-rope/`](jumping-rope/) | The system: rope format, vault, `jrope` CLI, adapters for Claude Code / Open WebUI / any OpenAI-compatible stack | 91 tests green |
| [`ropebench/`](ropebench/) | The benchmark: 4 strategies, planted-question scoring, scripted + live modes | 25 tests green |

```bash
# try it
pip install -e "./jumping-rope[dev]"
cd jumping-rope && python examples/demo_session.py

# reproduce the charts
pip install -e ./ropebench --no-deps
ropebench run --mode scripted --seeds 3 --turns 80
```

## Agent brain

Agents working in this repo get project skills from
[`.claude/skills/`](.claude/skills/):

- **`jumping-rope`** — the system's own skill: maintain `ROPE.md`
  continuously, archive to the vault, re-seed from the rope after any
  context clear (rope creation and storage, dogfooded).
- **`ponytail` + review/audit/debt/gain/help** — vendored from
  [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail)
  (MIT): the lazy-senior-dev discipline. All rope/storage code in this repo
  is written under it — simplest solution that works, stdlib before
  dependencies, one line before fifty.

Development plan (what's next, known limits, the live-model phase):
[`ropebench/ROADMAP.md`](ropebench/ROADMAP.md). Imported with full git
history from [jumping-rope](https://github.com/AlphaSaleAidan/jumping-rope)
and [ropebench](https://github.com/AlphaSaleAidan/ropebench) — both fully
merged to `main` (build, two adversarial campaigns, v1.1 modes, benchmark).
MIT.
