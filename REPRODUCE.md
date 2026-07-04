# REPRODUCE

Every number in the README traces to a row in [CLAIMS.md](CLAIMS.md). Here are
the exact commands to regenerate them from a fresh clone.

```bash
git clone https://github.com/AlphaSaleAidan/ropebench && cd ropebench
pip install -e ".[dev]"
```

## CI-tier (free, hermetic, deterministic — no network)

These reproduce the lead findings (C1–C6, C8) with no API cost.

```bash
# The statistically-hardened scripted sweep (5 seeds, n=150).
# Regenerates results/hardened-scripted/ — C1..C6.
jrope-bench run --runs 5 --turns 80 --out results/hardened-scripted
cat results/hardened-scripted/report_card.md   # paired CIs + age-stratified table

# B6: streaming-eviction cost modeled in-bench (C8).
pytest tests/test_b6.py -q

# Full hermetic suite + lint + types.
pytest -q && ruff check . && mypy --strict ropebench
```

The paired CIs are seeded (bootstrap seed 0, 10k resamples), so the exact
interval reproduces bit-for-bit.

## api-tier (paid — needs a budget)

C7 (live-model information use) and any frontier comparison make paid calls.
The runner refuses to start without a budget and prints a cost estimate first.

```bash
export JROPE_BENCH_API_BASE=https://openrouter.ai/api/v1
export JROPE_BENCH_API_KEY=sk-...
export JROPE_BENCH_BUDGET_USD=5.00     # required — refuses to run if unset

# Live sweep; responses cache under bench_cache/ so re-grading is free.
jrope-bench run --runs 3 --mode live --model anthropic/claude-haiku-4-5 \
  --out results/live-haiku
```

Or drive a local CLI model with no API metering:

```bash
jrope-bench run --runs 3 --mode live-cmd --cmd "claude -p --model haiku" \
  --out results/live-haiku
```

## Bring your own session

```bash
jrope-bench convert my-claude-session.jsonl bench.jsonl   # Claude Code → bench schema
jrope-bench run --transcript bench.jsonl --conditions rope,carry,summarize \
  --out results/mine
# post results/mine/report.json to prove your reproduction.
```

Bench transcript schema — one JSON object per line:
`{"role": "user"|"assistant", "content": "<text>"}`.

## Self-verification

The CI-tier block above was run on this branch; its output is pasted in
[BENCH_V2_REPORT.md](BENCH_V2_REPORT.md).
