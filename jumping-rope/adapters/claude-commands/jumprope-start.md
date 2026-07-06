---
name: jumprope-start
description: Start a live Jumping Rope for THIS session — creates .claude/jumprope/sessions/<session_id>/ROPE.md and unfreezes the statusline gauge.
---

# /jumprope-start — begin carrying this session on a rope

Every session gets its OWN rope. The statusline gauge reads
`.claude/jumprope/sessions/<session_id>/ROPE.md` for the current session id.

Steps (use these paths):

```bash
JR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/jumprope/sessions/${CLAUDE_CODE_SESSION_ID:-default}"
OPS=/ABS/PATH/jumprope.md/.claude/skills/jumping-rope/scripts/rope_ops.py
```

1. If `$JR/ROPE.md` already exists, do NOT re-init. Run
   `python3 "$OPS" status --root "$JR"`, report the rope's current fill to the
   user, and stop.
2. Ensure `$JR/env` exists; if missing, create it (mkdir -p first) with:
   ```
   JROPE_MODE=bound
   JROPE_BUDGET=2000
   JROPE_EMOJI=➰
   ```
   If it exists, leave it alone (mode is managed by /jumprope-mode).
3. Read the env values, then init:
   `python3 "$OPS" init --root "$JR" --budget "$JROPE_BUDGET"`
4. Seed the rope from THIS session so the gauge starts honest — log at
   minimum (all with `--root "$JR" --budget "$JROPE_BUDGET"`):
   - `log state "<current git branch>" --key branch`
   - `log state "<cwd / project>" --key cwd`
   - one `log goal "<what this session is working on>" --status active`
   - any decisions already made this session: `log decision "<d>" --reason "<r>"`
   - any unresolved threads: `log open "<o>" --priority 1`
5. Confirm to the user: rope live at `$JR/ROPE.md` (session-scoped), mode +
   budget + emoji, and that the statusline gauge is now tracking it — the
   emoji animates while the session works and freezes when idle.

From now on in this session, follow the jumping-rope operating loop: after
every meaningful change (edit, decision, discovered fact, blocker, completed
goal) log it to the rope immediately with `rope_ops.py log`; before/after any
compaction run `rope_ops.py jump` and re-seed from the printed rope alone.
When JROPE_MODE=unbound, pass `--budget 999999` to log/jump calls so nothing
is demoted; when bound, always pass the env's `JROPE_BUDGET`.
