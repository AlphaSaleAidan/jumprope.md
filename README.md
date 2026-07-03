# jumprope.md

Umbrella project for **Jumping Rope** — a two-tier context-handoff system for
LLM sessions — and the benchmark that drives its development. Both components
are vendored here with full git history for forking into downstream projects.

```
            turns / events                      the jump
 ┌────────┐  record_event   ┌───────────────┐  rope only   ┌───────────────┐
 │  LLM   │ ───────────────▶│  ROPE.md      │ ────────────▶│ fresh session │
 │ session│                 │  ≤2000 tokens │              │ (context      │
 └────────┘                 └──────┬────────┘              │  cleared)     │
      ▲                            │ demote                └──────┬────────┘
      │                     ┌──────▼────────┐   retrieve          │
      └─────────────────────│   TurboVec    │◀────────────────────┘
                            └───────────────┘
```

## Components

| Dir | What | Status |
|---|---|---|
| [`jumping-rope/`](jumping-rope/) | The system: rope file spec, compactor, TurboVec store, `jrope` CLI, adapters (Claude Code skill, Open WebUI pipe, OpenAI-compatible proxy) | 81 tests green; adversarially verified (8 broken → 8 fixed, see `ADVERSARIAL_REPORT.md`) |
| [`ropebench/`](ropebench/) | The effectiveness benchmark: 4 context regimes, distance-stratified probes, scripted (CI) + live modes | 25 tests green; first sweep complete |

## Headline numbers (measured)

- **Token density**: symbolic-en notation cuts 42.1% of prose tokens (o200k_base).
- **Post-jump payload**: 17–18% of the naive full-history payload.
- **Effectiveness** (scripted sweep, 3 seeds × 80 turns): rope **94%** state
  continuity — **100% at long distance** vs truncate 67% / summary compaction
  24% — at **52% of the oracle's token spend**, best accuracy-per-token of all
  four regimes.
- Known weak cell: decision recall 79% → fix plan in
  [`ropebench/ROADMAP.md`](ropebench/ROADMAP.md) (findings B1–B3).

## Development loop

Benchmark → localize the failure → fix in `jumping-rope/` → re-run
`ropebench` as the regression gate (`test_regime_ordering_claims`).
The phased plan to iron out the remaining bugs lives in
[`ropebench/ROADMAP.md`](ropebench/ROADMAP.md).

## Provenance

Imported with full history from
[AlphaSaleAidan/jumping-rope](https://github.com/AlphaSaleAidan/jumping-rope)
(branch `test/adversarial-v1` — includes all adversarial fixes) and
[AlphaSaleAidan/ropebench](https://github.com/AlphaSaleAidan/ropebench)
(branch `feat/ropebench-v1`). Each component keeps its own README, tests,
LICENSE (MIT) and CI workflow.
