# BENCH v2 REPORT — harden the numbers, lead with the benchmark

Campaign to turn early-stage findings into CI-bound claims, close B6, and make
the benchmark the front door. Repo note: the benchmark lives in **ropebench**
(the prompt assumed a monorepo `jumping_rope/bench/`); all work landed here, with
`jrope-bench` as the console script.

## Verdict summary

The headline changed, honestly. **Lead is now the summarization finding**
(large, CI-clears-zero, age-stratified), not the fragile Opus edge. The
rope-beats-carry-all claim is **scoped to live models** — with a literal reader
the rope significantly *trails* carry-all (−6.7%), a correction this campaign
surfaced. B6 is **closed by modeling** (not scoped out).

## Section ledger

| S | goal | outcome |
|---|---|---|
| S0 | cost guardrails + caching + markers | budget gate (refuses if unset, aborts if over), disk cache by (model,payload), pytest markers default/local/api. `pricing.py`, 7 tests |
| S1 | paired-CI statistical hardening | `stats.py` pure-stdlib bootstrap (10k, seeded), verdict from CI-clears-zero, claim_phrase writes parity when it doesn't; probes 26→30/seed, age tercile. 9 hand-computed tests |
| S2 | promote summarization to lead | README reordered: summarization → 1.35M-no-carry → quality-at-CI-strength → retrieval |
| S3 | close B6 | **modeled** (preferred path): `StreamingRopeRegime` drives the real `apply_streaming_policy`; streaming cost flat vs verbosity, 29% of full-history at 4× filler, loses on filler-free (honest). 3 known-answer tests |
| S4 | jrope-bench front door | `run --transcript`, `convert`, `--conditions`, `--runs`; report_card.md + report.json; BYO-schema; stub-endpoint e2e |
| S5 | claims audit | CLAIMS.md (11 rows + 3 corrections); README grep audit — every digit traces to a row |

## Key hardened numbers (n=150, 5 seeds, scripted, seeded bootstrap)

```
summarization by fact age (vs rope):
  early (n=65):  -20.0%  [-32.3%, -7.7%]   significant
  mid   (n=70):  -30.0%  [-42.9%, -17.1%]  significant
  late  (n=15):   +0.0%  [0%, 0%]          untouched

rope vs full-history: -6.7%  [-10.7%, -2.7%]  rope-WORSE (literal reader)
rope vs summary:     +22.7%  [+14.7%, +30.7%] rope-better
rope vs truncate:     +7.3%  [+0.7%, +14.7%]  rope-better
```

## Corrections made visible (CLAIMS.md)

1. ≤35% cost target — was a payload-snapshot metric, not a general bound.
2. Unbound economics — was adapter-only; now modeled in-bench (B6 closed).
3. Opus 96-vs-92 — single-seed (n=26), CI not established → directional only,
   not a headline.

## Exit criteria

- `pytest -q` (default tier): **60 passed**, ruff 0, mypy --strict clean.
- S1 paired-CI table + per-tercile breakdown: complete (above).
- S0 budget guard + cache: tested hermetically; live sweeps print an estimate
  and abort without a budget.
- S3: in-bench eviction model + known-answer test — path taken: **modeled**.
- jrope-bench demo (fixture + stub endpoint): `tests/test_frontdoor.py`.
- REPRODUCE.md self-verified for CI-tier (hardened sweep regenerated).
- CLAIMS.md complete; README grep audit passed.
