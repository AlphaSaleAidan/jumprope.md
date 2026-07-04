# Report 3 — tighter CIs + noise robustness (loop cycle 2)

- **Flagship CIs tightened to 20 seeds (n=600)**: summarization −22.7% [−28.5,−16.9] on
  early facts, −25.4% [−31.8,−18.9] on mid — bulletproof. Bootstrap coverage 0.9462 @ 100k trials.
- **T8 CONFIRMED**: rope is noise-robust — at 16× filler it holds 44% while truncate/summary
  collapse to 16%; the margin widens with filler. New chart on the umbrella README.
- 5 sub-theories now confirmed (T1,T2,T3,T4,T8); T5 (ordering) deferred to a live cycle.
- Suite green (66 tests), ruff+mypy clean. Research PR #5 updated.
