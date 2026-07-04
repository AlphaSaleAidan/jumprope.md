# Report 1 — kickoff + first wins (hour ~1)

**Email delivery blocked:** the Resend key pasted returns 403/1010 on all
endpoints (restricted key, no verified sending domain). Reports are logged here
instead; email retried periodically. Rotate the key + verify a domain to enable.

## Done
- **bench v2 MERGED to main** (statistical hardening). C7 live number landed:
  Haiku n=90 — rope trails full-history −4.0% [−8.9,−1.1] but beats summary
  +22.2% [+11.1,+31.1] at 60% of the cost.
- **Stats validated at scale**: 20,000 simulated experiments → bootstrap CI
  coverage 0.9492 vs 0.95 nominal. 0 determinism failures / 0 unanswerable
  probes across 5,000 seeds each.
- **T1 CONFIRMED**: rope advantage grows as a power law with session length —
  full-history O(n^1.34), rope O(n^0.73), advantage O(n^0.61). 4.5× cheaper at
  260 turns.
- **Higgsfield hero image** shipped to the umbrella README.

## Next
T2–T6 theories, massive repeated sweeps, more visuals, README upgrades.
