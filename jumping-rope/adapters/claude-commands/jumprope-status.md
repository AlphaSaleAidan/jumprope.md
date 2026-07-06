---
name: jumprope-status
description: Show whether THIS session's Jumping Rope is running (fill, mode, jumps, freshness) and run a quick live self-test of the rope mechanics.
---

# /jumprope-status — is the rope running, and does it work?

Two parts: report the live state, then prove the mechanics with a fast
round-trip test. Keep the whole thing under ~15 seconds.

```bash
JR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/jumprope/sessions/${CLAUDE_CODE_SESSION_ID:-default}"
OPS=/ABS/PATH/jumprope.md/.claude/skills/jumping-rope/scripts/rope_ops.py
```

## 1. Live status

- If `$JR/ROPE.md` is missing: report "rope NOT running for this session"
  and point at /jumprope-start — then still run the self-test below (the
  mechanics are independent of a live rope).
- If it exists, report in a compact table:
  - `python3 "$OPS" status --root "$JR"` → est_tokens / budget / mode
  - env from `$JR/env` (mode, budget, emoji)
  - jump count (`j:` in the ROPE.md header) and section line counts
    (STATE/GOALS/DECISIONS/DELTA/OPEN/KEYS)
  - freshness: seconds since ROPE.md's mtime — if it's older than ~10 min
    while the session has been active, flag that the operating loop has
    stalled (facts are accumulating in the transcript, not the rope)
  - gauge render check: pipe `{"session_id":"$CLAUDE_CODE_SESSION_ID"}` into
    `python3 /ABS/PATH/jumprope.md/jumping-rope/adapters/claude-statusline/statusline.py` and
    confirm it emits a bar (bound) or ∞ (unbound), not an error.

## 2. Quick self-test (temp dir, never touches the live rope)

Run the full write → demote → retrieve cycle in a throwaway root:

```bash
T=$(mktemp -d)
python3 "$OPS" init --root "$T" --budget 2000
python3 "$OPS" log decision "probe-alpha uses port 7777" --reason smoke --root "$T" --budget 60
python3 "$OPS" log decision "probe-beta uses port 8888" --reason smoke --root "$T" --budget 60
grep -q "probe-alpha" "$T/ROPE.md" && echo "KEYS-stub: OK"      # demoted → stub in KEYS
python3 "$OPS" query "probe-alpha" --root "$T" | grep -q RETRIEVED && echo "retrieval: OK"
python3 "$OPS" jump --root "$T" >/dev/null && echo "jump: OK"
rm -rf "$T"
```

PASS criteria (report each as a ✓/✗ line):
1. init creates a spec-conformant ROPE.md
2. the tiny budget forces demotion — the decisions land as `K{n}|…|ovf-…`
   stubs under `## KEYS` (write path + budget enforcement)
3. `query` returns a `RETRIEVED|…` line for the demoted fact (recall path)
4. `jump` completes and prints the rope (compaction path)

## 3. Verdict

One line: **RUNNING + HEALTHY** / **RUNNING but STALE (last write Xm ago)** /
**NOT RUNNING (mechanics OK — /jumprope-start to begin)** / **BROKEN: <which
check failed>**. If any self-test check fails, show the failing command's
output verbatim.
