---
name: jumping-rope
description: >
  Externalized session memory via a token-dense rope file (ROPE.md) plus a
  TurboVec overflow store. USE THIS SKILL AGGRESSIVELY whenever a session is
  long or will be long, whenever context is getting full or compaction is
  near, for multi-hour agent work, session handoff, memory between context
  clears, or when the user mentions running out of context. Maintain the rope
  continuously from the FIRST meaningful change — do not wait for context
  pressure. On any compaction or clear, re-seed entirely from ROPE.md.
---

# Jumping Rope — context handoff for long sessions

You are carrying session state in a rope file, not in the transcript. The
transcript is disposable; `ROPE.md` at the repo root is not. When context is
cleared ("the jump"), the rope is the ONLY context the fresh session gets.

## Operating loop

1. **On session start**: if `ROPE.md` exists at the repo root, read it FIRST
   and treat it as authoritative state. If it does not exist, run:

   ```bash
   python scripts/rope_ops.py init
   ```

2. **After every meaningful change** — a file edit, a decision, a discovered
   fact, a new blocker, a completed goal — record it immediately:

   ```bash
   python scripts/rope_ops.py log state "feature branch checked out" --key branch
   python scripts/rope_ops.py log goal "implement rope parser" --status active
   python scripts/rope_ops.py log decision "use sqlite-vec" --reason "zero server"
   python scripts/rope_ops.py log delta "compress prose before storing" --path src/rope.py
   python scripts/rope_ops.py log open "flaky test in CI" --priority 1
   ```

   Priorities: P0/P1 are never demoted out of OPEN — reserve them for facts
   that must survive every jump verbatim. P2/P3 may be demoted to TurboVec.

3. **Before/after any compaction or context clear**: run the jump and re-seed
   from its output alone:

   ```bash
   python scripts/rope_ops.py jump
   ```

   The printed rope is your entire carried context. Do not attempt to recall
   anything from the old transcript.

4. **On a cache miss** — you need detail the rope no longer contains (look in
   `## KEYS` for the stub) — query TurboVec instead of guessing:

   ```bash
   python scripts/rope_ops.py query "sqlite-vec decision"
   ```

5. **Check pressure** occasionally with `python scripts/rope_ops.py status`.

## Degraded mode

If the `jumping-rope` package is not installed, `rope_ops.py` still maintains
a spec-conformant `ROPE.md` (char-based token estimate) and demotes overflow
to `.rope_overflow.md` instead of TurboVec. `query` greps the overflow file.
Everything above still applies; install `pip install jumping-rope` to upgrade
in place — the rope file format is identical.

## Reading the rope

- `## STATE` — current world facts (cwd, branch, services). Trust these.
- `## GOALS` — glyph prefix: ✓ done, ▶ active, ✗ failed, ◌ pending.
- `## DECISIONS` — append-only `D{n}|date|decision|reason`. Never re-litigate
  a decision recorded here without new information.
- `## DELTA` — what changed where: `path|class|summary`.
- `## OPEN` — unresolved threads `O{n}|P{p}|text`, P0 = drop everything.
- `## KEYS` — stubs for demoted detail: `K{n}|topic|key`. Retrieval key goes
  to `rope_ops.py query`.

## Worked example rope

```markdown
# ROPE v1 | sess:a1b2c3d4e5f6 | j:2 | t:2026-07-03T18:00:00Z
## LEGEND
glyphs: ✓=done ▶=active ✗=failed ◌=pending →=yields/then ∵=because +=and w/=with w/o=without |=field-sep
records: D{n}|date|decision|reason · K{n}|topic|key · P0..P3=priority
## STATE
cwd:/root/acme-api
branch:feat/rate-limiter
services:redis:6379 ✓
## GOALS
✓ G1|impl token-bucket limiter
▶ G2|wire limiter into middleware
◌ G3|load-test 500 rps
## DECISIONS
D4|2026-07-03|redis INCR+EXPIRE over lua script|simpler, atomic enough
## DELTA
src/middleware/limit.py|add|token bucket, 100 req/min default
tests/test_limit.py|add|8 cases incl burst
## OPEN
O2|P1|EXPIRE race under concurrent INCR — needs lua after all?
O3|P2|choose limit for /auth endpoints
## KEYS
K1|D1/2026-07-01/project kickoff scope|tv-8a0b8122ec20
K2|early middleware design notes|tv-6587e6b627c1
```

Reading this after a jump: you are on `feat/rate-limiter`, the limiter is
built and tested, wiring it into middleware is the active goal, there is a
P1 race condition to resolve, and the kickoff scope is retrievable with
`rope_ops.py query "project kickoff scope"`.

## Rules

- The rope has a HARD budget (default 2,000 tokens). `rope_ops.py` enforces
  it by demoting oldest DECISIONS/DELTA and P2/P3 OPEN items. LEGEND, STATE
  and GOALS are never demoted — keep them tight.
- One line per fact. Use the legend notation: no articles, no filler,
  `→` for causality, glyphs for status.
- Record decisions WITH reasons at the moment they are made. Future-you
  cannot reconstruct a reason from the transcript — it will be gone.
- Tool output (tracebacks, diffs, config dumps, log tails) often holds
  the ONLY copy of a critical value — a port, a digest, a threshold, a
  latency. Log such values as facts VERBATIM even when the surrounding
  output looks routine: measured, an unhinted scribe skims past ~1 in 5
  of them (ropebench T11), and summarization recovers none of them.
- Never paste secrets into the rope. It is a plain file on disk.
