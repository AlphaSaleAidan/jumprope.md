# CLAIMS — every quantitative claim, with its evidence

One row per number that appears in the README or docs. If a row has no
artifact, the claim is deleted or measured — there is no third option.
Regenerate CI-tier rows from a fresh clone with the commands in
[REPRODUCE.md](REPRODUCE.md).

| # | claim | value | n | 95% CI | artifact | regenerate |
|---|---|---|---|---|---|---|
| C1 | **Summarization destroys OLD facts** (early-introduced) vs rope | −22.7% | 260 | [−28.5%, −16.9%] | `results/bigrun-20seed/result.json` (5-seed free-tier in `results/hardened-scripted/`) | `jrope-bench run --runs 20 --turns 80` |
| C2 | Summarization destroys MID-age facts vs rope | −25.4% | 280 | [−31.8%, −18.9%] | same | same |
| C3 | Summarization leaves RECENT facts intact vs rope | +0.0% | 60 | [0%, 0%] | same | same |
| C4 | Rope beats summary overall (scripted) | +21.7% | 600 | [+17.7%, +25.7%] | same | same |
| C5 | Rope beats truncate overall (scripted) | +7.0% | 600 | [+3.7%, +10.3%] | same | same |
| C6 | Rope trails full-history with the LITERAL reader (scripted) | −6.0% | 600 | [−8.0%, −4.2%] | same | same |
| C7 | Rope trails full-history with a LIVE model but beats summary (Haiku) | −4.0% vs carry / +22.2% vs summary | 90 | [−8.9%, −1.1%] / [+11.1%, +31.1%] | `results/live-hardened-haiku/result.json` | `jrope-bench run --runs 3 --mode live-cmd --cmd "claude -p --model haiku" --conditions rope,carry,summarize` |
| C8 | Streaming-unbound cost on a chatty transcript (chatty=16) | 29% of full-history | — | (measurement, not accuracy) | `tests/test_b6.py` | `pytest tests/test_b6.py` |
| C9 | Notation density reduction vs prose (symbolic-en) | 42.1% | — | fixed fixture | jumping-rope `tests/test_density.py` | `pytest -k density` (jumping-rope) |
| C10 | Real 117-turn transcript token size | 1.35M tok | — | existence proof | `results/live-haiku-full` / Phase 5 | `jrope-bench run --transcript <session>` |
| C11 | Rope carries the same real session in | ~75K tok (18× smaller) | — | same | same | same |
| C12 | Bootstrap CI coverage (statistical validity) | 0.9462 | 100,000 | ~0.95 nominal | `tests/test_stats_calibration.py` | `pytest -m local -k coverage_full` |
| C13 | **T8** — rope is noise-robust: acc at 16× filler vs lossy baselines | rope 44% vs truncate/summary 16% | 3 seeds | rope−truncate margin 7pt→28pt as filler grows | `tests/test_theory_t8.py` | `pytest -m local tests/test_theory_t8.py` |
| C14 | **T7** — flat semantic recall of a specific fact collapses under near-duplicates | 100%→0% (N=0→64); rope exact-fetch 100% throughout | 8 seeds × 20 targets | tracks/undershoots chance k/(N+1) | `tests/test_theory_t7.py`, `research/exp_t7_distractors.py` | `pytest -m local tests/test_theory_t7.py` |
| C15 | **T7** — AI-native coding makes semantic search fail *faster* (widens exact-vs-semantic gap) | flat 48%→33% at N=4 (symbolic→ai-native); rope 100% both | 8 seeds × 20 targets | — | same | same |

## Corrected claims (correction history, kept visible)

- **≤35% cost target (bench v1):** originally stated as a general cost bound.
  Corrected: 35% is a *post-jump payload snapshot* metric (adapter tests,
  17–18%); under the bench's pay-every-turn model the figure is ~54% (live)
  / condition-dependent. See C7 and the report cards.
- **Unbound-mode economics (B6):** originally rested on adapter tests
  (unlabeled). Corrected: now modeled in-bench (C8) — streaming cost is
  flat vs verbosity and 29% of full-history at 4× filler, but *loses* on
  filler-free streams. No unbound number appears unlabeled.
- **Opus rope-beats-carry-all (96% vs 92%):** single-seed observation
  (n=26), CI **not established** — reported as directional only, consistent
  with long-context degradation, NOT as a hardened superiority claim. A
  multi-seed frontier run is required to harden it.
