# DECISIONS

Micro-decisions made where the spec left room, and why.

## Rope format

1. **Demoted lines leave their stub in `## KEYS` only** (not in-place in the
   source section). An in-place stub plus a KEYS entry would double-count
   tokens; the KEYS line *is* the one-line stub with a retrieval key, and its
   topic field carries a ~6-word hint of the demoted content.
2. **Keyring coalescing.** `## KEYS` itself is not in the never-demote set
   (only LEGEND/STATE/GOALS are). When everything demotable is drained and
   the rope is still over budget, the oldest KEYS stubs are bundled into a
   single TurboVec "keyring" record and replaced by one stub. Retrieval
   becomes two-hop but nothing is ever lost. Without this, KEYS grows without
   bound and small budgets eventually become unsatisfiable.
   *(Amended after adversarial finding A1a:)* the keyring stub's topic is a
   digest `KR:tok1,tok2,… [+n]` carrying one significant token per
   transitive member (48-token budget, newest first) — a bare
   `keyring:N demoted keys` label left bundled members unreachable to a
   literal cold reader.
3. **Demotion order across sections** is DECISIONS → DELTA → OPEN (P3 before
   P2), oldest-first within each. The spec fixes oldest-first per section and
   the P2/P3-only rule for OPEN; the cross-section order is our deterministic
   choice, asserted by `test_demotion_order_decisions_then_delta_then_open`.
4. **DELTA is a change map**: a second event for the same path replaces the
   existing line (newest change class + summary win) rather than appending.
5. **Field sanitization**: free text is made line-safe on append (`|` → `/`,
   newline → `; `), so the pipe-delimited line grammar can never be broken by
   content. Parsing is strict; sanitization happens at write time.
6. **Goal numbering is per-rope and monotonic** (`max+1`), so numbers stay
   stable after demotion elsewhere; GOALS itself is never demoted.

## Tokens

7. **Bundled tokenizer vocabulary.** tiktoken downloads the o200k_base BPE
   file on first use, which would violate the zero-network test requirement.
   The 3.5 MB vocabulary is bundled at `jumping_rope/_data/tiktoken_cache/`
   and `TIKTOKEN_CACHE_DIR` defaults to it. The test suite additionally
   installs a socket guard that fails any test attempting a non-local
   connection.

## TurboVec

8. **One table, two search paths.** Embeddings are stored as little-endian
   float32 blobs (sqlite-vec's serialization). When the sqlite-vec extension
   loads, cosine distance runs in SQL; otherwise a pure-Python brute-force
   path scans the same table. Databases are interchangeable between paths.
9. **`check_same_thread=False`** on the SQLite connection: sessions are
   single-writer by design but may be driven from a different thread (ASGI
   test clients, thread pools).
10. **HashEmbedder** = signed feature hashing of word unigrams/bigrams and
    character trigrams into 256 dims, L2-normalized, md5-based — fully
    deterministic across platforms and dependency-free.
11. **Exact-ranking parity between backends is not asserted** — float32 SQL
    vs float64 Python produce different tie-breaks among near-zero scores.
    Tests assert both backends agree on the clear best match.

## Session / cadence

12. **Turn accounting is explicit** (`note_turn`), separate from
    `record_event`: an agent may record several meaningful changes in one
    conversational turn. The chat adapters count one turn per request and use
    the naive history size as the live-context estimate.
13. **Adapters archive the latest user message and assistant reply
    full-fidelity into TurboVec** each request (tier 2) with a K-line stub;
    only their gists ride along in the rope via stub topics. This keeps the
    rope for state, not chat logs.
14. **Post-jump live estimate resets to the rope's own token count**, since
    the rope is the only carried context after a jump.
15. **The 20 % outbound-vs-naive assertion is made at the final jump** of the
    adapter tests. The rope has a fixed floor (legend + anchors + last user
    message), so early in a conversation the ratio is mathematically higher;
    as the naive history grows the ratio falls below 20 % and stays there.
    Both measured ratios are printed by the tests.

## Adapters

16. **The pipe's upstream is injectable** (`pipe.upstream_fn`) so the unit
    test fakes the upstream with a local function, per spec. The default
    implementation posts with urllib to keep the file self-contained.
17. **rope_ops.py degraded mode** estimates tokens as `len(text) // 4` (no
    tiktoken without the package) and demotes to `.rope_overflow.md` with
    `ovf-N` keys; `query` is substring search over the overflow file. The
    produced ROPE.md is spec-conformant — asserted by parsing it with the
    real parser in tests.

## Packaging

18. **cjk-dense measured honestly**: under o200k_base it is *not* better than
    symbolic-en (see README table) because single CJK characters often cost
    more o200k tokens than abbreviated English. The profile ships as
    spec'd, behind a config flag, with measured numbers and a warning.
19. **Python 3.11 as minimum**, CI matrix on 3.11 + 3.12.

## v1.1 — bound/unbound modes (user feedback: "compaction stops the workflow")

20. **Two first-class modes.** `rope_budget_tokens=0/None` = **unbound**: no
    demotion pressure; the rope is the persistent record and grows as needed.
    Eviction moves to the transcript side: `apply_streaming_policy` drops
    each chat message from the outgoing history as soon as its content is
    archived (coverage = content-addressed key exists in TurboVec). The
    Python API default stays bound (2000) for compatibility; the chat
    adapters default to unbound.
21. **ai-native profile** = symbolic-en + adaptive per-session phrase
    dictionary (`§a…`, declared in the legend, bigram-disjoint entries,
    capped at 24). Coded on the rope only — the compactor expands codes
    before TurboVec storage so retrieval matches natural language. State
    persists in session.json.
22. **Turn provenance.** `SessionMeta.total_turns` stamps archives and their
    K-lines (`t{n}·topic`) and a `turn` column on TurboVec records (ALTER
    TABLE migration for old DBs) — the key log lines up with the context log.
23. **Streaming outbound can exceed a tiny naive history** by the rope's
    fixed overhead (same effect as A13); the flat-growth property is what
    matters and is what tests assert.
