# CLAIMS — every quantitative claim, with its evidence

One row per number that appears in the README or docs. If a row has no
artifact, the claim is deleted or measured — there is no third option.
Regenerate CI-tier rows from a fresh clone with the commands in
[REPRODUCE.md](REPRODUCE.md).

| # | claim | value | n | 95% CI | artifact | regenerate |
|---|---|---|---|---|---|---|
| C1 | **Summarization destroys OLD facts** (early-introduced) vs rope | −20.0% | 65 | [−32.3%, −7.7%] | `results/hardened-scripted/report.json` | `jrope-bench run --runs 5 --turns 80 --out results/hardened-scripted` |
| C2 | Summarization destroys MID-age facts vs rope | −30.0% | 70 | [−42.9%, −17.1%] | same | same |
| C3 | Summarization leaves RECENT facts intact vs rope | +0.0% | 15 | [0%, 0%] | same | same |
| C4 | Rope beats summary overall (scripted) | +22.7% | 150 | [+14.7%, +30.7%] | same | same |
| C5 | Rope beats truncate overall (scripted) | +7.3% | 150 | [+0.7%, +14.7%] | same | same |
| C6 | Rope trails full-history with the LITERAL reader (scripted) | −6.7% | 150 | [−10.7%, −2.7%] | same | same |
| C7 | Rope ≈ full-history with a LIVE model (Haiku, information-use) | see report.json | 78 | pending hardened rerun | `results/live-haiku-full/` | `jrope-bench run --runs 3 --mode live-cmd --cmd "claude -p --model haiku"` |
| C8 | Streaming-unbound cost on a chatty transcript (chatty=16) | 29% of full-history | — | (measurement, not accuracy) | `tests/test_b6.py` | `pytest tests/test_b6.py` |
| C9 | Notation density reduction vs prose (symbolic-en) | 42.1% | — | fixed fixture | jumping-rope `tests/test_density.py` | `pytest -k density` (jumping-rope) |
| C10 | Real 117-turn transcript token size | 1.35M tok | — | existence proof | `results/live-haiku-full` / Phase 5 | `jrope-bench run --transcript <session>` |
| C11 | Rope carries the same real session in | ~75K tok (18× smaller) | — | same | same | same |

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
