# Jumping Rope

**Two-tier context handoff for LLM sessions.** Stop replaying transcripts;
carry a rope.

LLM context windows are mostly dead weight: replaying an entire transcript to
preserve state wastes tokens and degrades reasoning. Jumping Rope replaces
transcript-carrying with externalized memory:

- **Tier 1 — the rope (`ROPE.md`)**: a single, continuously maintained
  markdown ledger in a token-dense notation, under a **hard token budget**
  (default 2,000). When context is cleared — *the jump* — the rope is the
  ONLY context handed to the fresh session.
- **Tier 2 — TurboVec**: an embedded local vector store (single SQLite file)
  holding everything demoted out of the rope. Missing detail is fetched back
  by key or semantic search — a cache-miss lookup, not a context reload.

Compaction is 3–5× more aggressive than typical auto-compaction: jump when
the live context exceeds `jump_threshold_tokens` (default 12,000) **or**
every `jump_every_n_turns` (default 8), whichever comes first.

## Why "Jumping Rope"

Picture the session as a jumper and the context window as the ground: every
few turns the accumulated transcript is swept away beneath it, and the
session jumps — clearing the wipe, carrying nothing but the rope in its
hands. The rope is small, dense, and continuously re-woven; the session can
keep jumping indefinitely because it never tries to carry the ground with it.

## Architecture

```
            turns / events                      the jump
 ┌────────┐  record_event   ┌───────────────┐  rope only   ┌───────────────┐
 │  LLM   │ ───────────────▶│  ROPE.md      │ ────────────▶│ fresh session │
 │ session│                 │  ≤2000 tokens │              │ (context      │
 └────────┘                 │  LEGEND STATE │              │  cleared)     │
      ▲                     │  GOALS DECIS. │              └──────┬────────┘
      │                     │  DELTA OPEN   │                     │
      │                     │  KEYS ────────┼──── stubs           │ cache miss
      │ RETRIEVED|key|...   └──────┬────────┘                     │
      │                            │ demote (oldest / P2-P3)      │
      │                     ┌──────▼────────┐                     │
      └─────────────────────│   TurboVec    │◀────────────────────┘
                            │ sqlite(-vec)  │   get(key) / search(query)
                            └───────────────┘
```

The rope file has seven fixed sections. `LEGEND`, `STATE` and `GOALS` are
never demoted; `DECISIONS`/`DELTA` demote oldest-first and `OPEN` demotes
only P2/P3 items, each leaving a one-line stub in `## KEYS` with a TurboVec
retrieval key.

## Two modes: bound and unbound

| | **bound** (`rope_budget_tokens=2000`) | **unbound** (`rope_budget_tokens=0`) |
|---|---|---|
| The rope | hard token cap; old detail demotes to TurboVec | grows as needed (still dense) — nothing demotes |
| What gets evicted | rope content (into the vault) | the **transcript**, continuously, as soon as each message is captured |
| Context clear | episodic jumps every ~8 turns / ~12k tokens | continuous — outbound is always `[rope] + current message` |
| Detail access | retrieval (cache miss) | everything verbatim on the rope |
| Failure surface | retrieval recall (see limitations) | rope size on very long sessions |

**Use bound when:** the model's context window is small or expensive; the
agent runs unattended for days and cost dominates; sessions are noisy (lots
of churn that will never be asked about again); you're metering an API
middleware where every token is billed.

**Use unbound when:** the work is interactive and a retrieval miss would
stall you (decisions and facts stay verbatim on the rope — no recall risk);
the model has a large, cheap context window; sessions are hours-to-days, not
weeks; you want the key log to double as a browsable index of the whole
conversation (every archived message gets a `t{turn}`-stamped K-line, so
`## KEYS` lines up with the context log).

Switch per session: `jrope init --mode unbound`, `JumpConfig.unbound()`, the
pipe's `MODE` valve, or the proxy's `JROPE_MODE` env. The pipe and proxy
default to **unbound** (streaming eviction); the Python API defaults to
**bound** for backward compatibility.

**Stack them.** The modes compose as lifecycle phases: work **unbound**
while the session is hot (zero recall risk), then **retire** it when it
goes cold —

```bash
jrope retire --budget 2000   # or session.retire(budget_tokens=2000)
```

— one explicit demotion pass moves everything over budget into TurboVec
and emits the compact bound artifact; the session stays bound afterwards.
Never automatic: surprise mid-flow compaction is exactly what unbound mode
exists to avoid.

When `## KEYS` itself grows past what the budget allows, the oldest stubs
coalesce into a **keyring**: one TurboVec record bundling the stubs, replaced
in the rope by a single digest stub `K{n}|KR:tok1,tok2,… [+n]|{key}` carrying
one significant token per transitive member (newest members win a 48-token
digest budget; `+n` marks overflow). A cold reader — human or model — matches
its question against the digest, retrieves the keyring, and recurses into the
member stubs it lists. Adversarially verified: a literal-minded cold agent
recovers 20/20 planted facts through a hostile-compaction rope with keyring
generations 4 deep (see `ADVERSARIAL_REPORT.md`, finding A1).

## Quickstart 1 — Python library

```bash
pip install jumping-rope
```

```python
from jumping_rope import JumpingRopeSession

s = JumpingRopeSession("./jrope-data")
s.record_event("goal", "ship the rate limiter", status="active")
s.record_event("decision", "redis INCR over lua", reason="atomic enough")
if s.should_jump():
    fresh_context = s.jump()        # the rope — the ONLY carried context
print(s.retrieve("why redis INCR"))  # cache-miss lookup from TurboVec
```

CLI equivalent: `jrope init && jrope log decision "redis INCR over lua"
--reason "atomic enough" && jrope status && jrope jump && jrope query "INCR"`.

## Quickstart 2 — Claude Code skill

Copy `adapters/claude-skill/jumping-rope/` into your skills directory
(e.g. `.claude/skills/`). The skill instructs Claude to maintain `ROPE.md`
at the repo root via `scripts/rope_ops.py` after each meaningful change and
to re-seed itself from the rope alone after any compaction. Works without
the package installed (degraded mode: no TurboVec, overflow goes to
`.rope_overflow.md`).

## Quickstart 3 — Open WebUI pipe

Paste `adapters/openwebui/jumping_rope_pipe.py` as a Pipe Function
(Workspace → Functions) in an environment where `jumping-rope` is installed.
Set the valves: upstream base URL (OpenRouter/Ollama/LiteLLM), model id,
thresholds, notation profile, data dir. On threshold breach the outgoing
history is replaced by `[system: rope] + [last user message]`.

## Quickstart 4 — OpenRouter / custom stack proxy

```bash
pip install "jumping-rope[adapters]"
export JROPE_UPSTREAM_URL=https://openrouter.ai/api/v1
export JROPE_UPSTREAM_KEY=sk-or-...
uvicorn adapters.openrouter.proxy:app --host 0.0.0.0 --port 8100
```

Point any OpenAI-compatible client at `http://localhost:8100/v1` and route
sessions with the `X-JRope-Session` header (falls back to a hash of the
first user message). Docker:

```yaml
# docker-compose.yml
services:
  jrope-proxy:
    image: python:3.12-slim
    working_dir: /app
    volumes: [".:/app"]
    command: >
      sh -c "pip install -e '.[adapters]' &&
             uvicorn adapters.openrouter.proxy:app --host 0.0.0.0 --port 8100"
    environment:
      JROPE_UPSTREAM_URL: https://openrouter.ai/api/v1
      JROPE_UPSTREAM_KEY: ${OPENROUTER_KEY}
    ports: ["8100:8100"]
```

## Notation profiles & tokenizers

The rope is written in a pluggable density notation (`NotationProfile`).
Two profiles ship; numbers below are **measured** by the test suite
(`tests/test_density.py`, fixture of identical facts) under **o200k_base**,
the bundled reference tokenizer:

| Profile       | Fixture tokens | Reduction vs prose | Legend cost |
|---------------|---------------:|-------------------:|------------:|
| plain prose   | 140            | —                  | —           |
| `symbolic-en` | 81             | **42.1%**          | 97 tokens   |
| `cjk-dense`   | 83             | 40.7%              | 119 tokens  |
| `ai-native`   | = symbolic-en on one-off text; **−17.5% more on repetitive sessions** (966 → 797 rope tokens, 30 recurring events) | | 97 + dictionary |

`ai-native` is symbolic-en plus an **adaptive per-session dictionary**: it
mines the session's own recurring phrases and assigns them short codes
(`§a`, `§b`, …) declared once in the legend — LZ-style compression whose
dictionary the reader model can see. Content is expanded back to natural
language before it reaches TurboVec, so retrieval is unaffected. The
dictionary persists across restarts with the session.

**Honest caveat:** under o200k_base, `cjk-dense` is *not* better than
`symbolic-en` — single CJK characters frequently cost as much as or more
than abbreviated English. CJK savings vary strongly by tokenizer; measure
with yours before enabling it (`notation_profile="cjk-dense"`).

Measured end-to-end payload effect (adapter tests, printed on every run):
at the final jump the outbound payload is **17.3%** (pipe) / **17.8%**
(proxy) of the naive full-history payload, and it keeps falling as the naive
history grows while the rope stays flat.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `rope_budget_tokens` | 2000 | hard cap (bound mode); **0/None = unbound mode** |
| `jump_threshold_tokens` | 12000 | bound mode: jump when est. live context exceeds this |
| `jump_every_n_turns` | 8 | bound mode: jump at least this often |
| `notation_profile` | `symbolic-en` | or `cjk-dense`, `ai-native` |

**Minimum budget.** A budget below the satisfiable minimum is rejected at
construction with a `ValueError` naming the computed minimum:
`minimum_budget_tokens(profile) = fixed floor (legend + header + anchors) +
64 tokens headroom` — **219 tokens** for `symbolic-en` under o200k_base
(measured floor: 155, regression-pinned in the adversarial suite).

Embedders: `HashEmbedder` (default; deterministic, dependency-free) or
`SentenceTransformerEmbedder` (`pip install "jumping-rope[st]"`). The
sqlite-vec extension (`[vec]` extra) accelerates search when present; a
pure-SQLite brute-force fallback keeps everything working without it.

## Limitations (measured, adversarial suite)

- **Hash embeddings miss paraphrases under near-duplicate load.** With 200
  distractors differing from a true record by one token (port numbers,
  negation), top-3 semantic search finds the record for verbatim and
  near-verbatim queries but **not** for a paraphrase ("which port does the
  sentinel service keep open…") — 67% hit rate across the three query styles
  (finding A12). One-token differences are near-invisible to bag-of-ngram
  hashing. Exact-key retrieval is immune (keys are content-addressed). If
  you need paraphrase-robust recall, install the `[st]` extra and use
  `SentenceTransformerEmbedder`.
- **Keyring depth vs. literal readers.** Facts buried deeper than ~3 keyring
  generations are beyond a literal reader's stub-following recursion; they
  remain retrievable via semantic search and exact keys (finding A1,
  recovery-path table in `ADVERSARIAL_REPORT.md`).
- **Crash semantics are at-least-once.** A crash between a TurboVec write
  and the rope save can leave a fact both in the rope and in the store;
  content-addressed keys guarantee the duplicate collapses on the next
  demotion (findings A9/A10). Nothing is ever lost, but readers may briefly
  see a fact twice.

## Development

```bash
pip install -e ".[dev]"
ruff check .              # 0 issues
mypy --strict jumping_rope
pytest -q                 # zero network: socket-guarded, bundled tokenizer
python examples/demo_session.py
```

MIT license. Micro-decisions are documented in [DECISIONS.md](DECISIONS.md).
