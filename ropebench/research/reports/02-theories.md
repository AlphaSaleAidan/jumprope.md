# Report 2 — four sub-theories confirmed (hour ~3)

## Confirmed (each with regression test + journal)
- **T1** value grows with session length — full-history O(n^1.34), rope O(n^0.73),
  advantage O(n^0.61); 4.5× cheaper at 260 turns.
- **T2** density has a floor — ai-native §-coding drops literal recall 93%→82%.
- **T3** structure beats a flat dense blob — 96% vs 62% at long distance (34pt gap, all in old facts).
- **T4** tighter budget wins (counterintuitive) — efficiency 25.3 @ 400 tok vs 5.6 @ 3600.

## Validated
- Bootstrap CI coverage 0.9492 over 20k trials (100k rerun in flight).

## Shipped
- `THEORY.md` (upgraded core claim + composed design principle), research PR #5,
  Higgsfield hero image + scaling line-chart on the umbrella README.

## Next
T5 (ordering), T6 (capability × density — needs live), tighter CIs from the
20-seed run, more visuals, README polish.
