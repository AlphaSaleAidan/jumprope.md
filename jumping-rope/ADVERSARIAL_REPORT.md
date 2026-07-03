# ADVERSARIAL REPORT — "Break the Rope" v1

Branch `test/adversarial-v1`. All attacks live in `tests/adversarial/` as
deterministic, zero-network pytest tests. Verdicts: **BROKEN** (attack
succeeded against the pre-attack code), **HELD** (attack failed), **FIXED**
(broken, then fixed in core; the red test was committed before the fix).

## Summary

| # | Sev | Attack | Expected | Actual (pre-fix) | Verdict |
|---|-----|--------|----------|------------------|---------|
| A1 | P0 | Cold agent recovers planted facts through the keyring two-hop path | ≥19/20 recovered, ≥5 specifically via keyring hop | 17/20 recovered, **0 via keyring** — the keyring was dead code masked by semantic search | **FIXED** |
| A1a | P0 | Every keyring stub digests ALL member topics | 100% member coverage | Stub said `keyring:N demoted keys` — **0/69 members covered (0%)** | **FIXED** |
| A2 | P1 | Budget below the fixed floor rejected loudly at config time | ValueError with computed minimum | Accepted silently; first write raised RopeBudgetError mid-session | **FIXED** |
| A3 | P2 | Fixed floor pinned absolutely | ≤175 tokens | Measured 155 tokens (o200k_base) | **HELD** |
| A4 | P2 | Keyring death spiral: 500 events at budget 600 | KEYS bounded, linear growth, nothing lost | Max 3 KEYS lines, 533 records/500 events, 25/25 spot-checks recovered | **HELD** |
| A5 | P1 | Fake record prefixes (`D99\|...`), glyphs, pipes in content | No phantom records, no field shift | Write-time sanitization (`\|`→`/`) held | **HELD** |
| A6 | P0 | Rope anchors as DELTA path / STATE key / session id | Parser unaffected | `## KEYS` as path/key rendered an **unparseable rope**; `sess:evil \| j:9` corrupted the header | **FIXED** |
| A7 | P0 | Hostile characters: CR, VT, FF, FS/GS/RS, NEL, U+2028/9, nulls, ZWJ, RTL, 10KB lines | Round-trip integrity, budgets hold | Every non-`\n` line break Python `splitlines()` honors **split records and broke parsing**; nulls/ZWJ/RTL/10KB held | **FIXED** |
| A8 | P2 | `<script>`, `javascript:` links, fenced blocks swallowing sections | Structure parses identically | One-line records + sanitization: no payload owns a line | **HELD** |
| A9 | P0 | Kill mid-jump (put raises after N=0,1,3 writes) | No fact stranded; disk rope always parses | Victim popped from rope **before** the store write — content lost from the live session | **FIXED** |
| A10 | P1 | Double jump / re-demotion idempotency | No duplicate records, stable keys | Random keys meant crash-retry duplicated records | **FIXED** |
| A11 | P1 | Two sessions, one store, two threads (50 ops each) | Isolation, no uncaught errors | `InterfaceError: bad parameter or other API misuse` — sqlite "serialized" mode does not protect interleaved cursor use | **FIXED** |
| A12 | P2 | 200 near-duplicate distractors (one-token diffs: numbers, negation) | Exact key immune; semantic rate documented | Exact key immune. Top-3: verbatim ✓, near-verbatim ✓, paraphrase ✗ (67%) — documented in README limitations | **HELD** (limit documented) |
| A13 | P2 | 8K-token LAST user message through pipe and proxy | Jump fires, message never truncated, rope cap applies to rope only | Held: rope portion 259 tokens, giant message byte-identical | **HELD** |

**Totals: 8 broken → 8 fixed, 6 held, 0 open sign-offs, 0 xfail.**

## A1 — recovery-path table (final post-fix run)

60-turn hostile session, budget 600, keyring generation depth **4**,
digest coverage **67/67 members (100%)**, recovery **20/20**:

| Path | Facts | Count |
|------|-------|------:|
| rope (verbatim in carried context) | F17 F18 F19 F20 | 4 |
| direct key stub | F15 F16 | 2 |
| **keyring hop** | F08 F09 F10 F11 F12 F13 F14 | **7** |
| semantic fallback | F01 F02 F03 F04 F05 F06 F07 | 7 |

Residual (documented, not a defect): facts buried deeper than the cold
agent's max recursion (3 keyring generations) are recovered by the semantic
fallback, not the literal hop. Their digest tokens still gate correctly at
the top level; the two-hop contract holds for everything ≤3 generations deep.

## A3 — measured floor

Empty rope (legend + header + anchors), o200k_base: **155 tokens**.
Pinned in `tests/adversarial/test_starvation.py` at 175 (+10% headroom)
with the 450 absolute cap. Minimum satisfiable budget =
`minimum_budget_tokens(profile)` = floor + 64 headroom = **219** for
`symbolic-en`.

## A12 — hash-embedding limit (documented in README)

200 one-token-off distractors against one true record, top-3 semantic:

| Query style | True record in top-3 |
|-------------|----------------------|
| verbatim | yes |
| near-verbatim (stopwords dropped) | yes |
| paraphrase ("which port does…") | **no** |

Hit rate 67%. One-token differences (numbers, negation) are near-invisible
to bag-of-ngram hashing: `port 4000 open` vs `port 4000 closed` differ by
one trigram cluster. Exact-key retrieval is immune (content-addressed
keys). Deployments needing paraphrase robustness should use the `[st]`
extra (`SentenceTransformerEmbedder`).

## Fixes shipped (each with its red test committed first)

1. **A1/A1a** — keyring stubs now carry `KR:tok1,tok2,… [+n]`: one
   significant token per transitive member (tag-like tokens preferred),
   deduplicated, newest members win a 48-token digest budget, overflow
   marked `+n`. (`compactor.build_keyring_digest`)
2. **A2** — `minimum_budget_tokens(profile)`; ValueError at session
   construction (both constructor configs and configs loaded from disk),
   before any filesystem writes.
3. **A6/A7** — `sanitize_field` neutralizes every `splitlines()` boundary;
   `sanitize_line_leading` replaces leading `#` runs with fullwidth `＃`
   and enforces non-empty line-leading fields; `sanitize_session_id`
   restricts ids to `[A-Za-z0-9._-]`.
4. **A9/A10** — demotion and keyring coalescing write to TurboVec BEFORE
   mutating the rope; keys are content-addressed
   (`sha1(session|section|content)`) with `INSERT OR IGNORE`, so
   crash-retry is idempotent and re-demotion cannot duplicate records.
5. **A11** — an `RLock` serializes all TurboVec connection use.

## Suite state after the campaign

Original 52 tests: green, unweakened. Adversarial: 29 tests, green,
0 skipped, 0 xfail. `ruff check .` clean, `mypy --strict jumping_rope`
clean. Full output in the PR.
