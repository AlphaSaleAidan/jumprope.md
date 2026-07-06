---
name: jumprope-mode
description: Switch THIS session's Jumping Rope between BOUND (hard token cap, oldest detail vaulted) and UNBOUND (no ceiling) — shows both options.
---

# /jumprope-mode — pick bound or unbound

Mode is per-session (matching the jumprope design: "two modes — pick per
session").

```bash
JR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/jumprope/sessions/${CLAUDE_CODE_SESSION_ID:-default}"
```

1. Read the current mode from `$JR/env` (defaults: bound, budget 2000,
   emoji ➰ if the file is missing).
2. Ask the user with the AskUserQuestion tool — exactly two options, and mark
   the currently active one in its description:
   - **Bound** — hard cap (JROPE_BUDGET tokens, default 2000). Oldest
     DECISIONS/DELTA and P2/P3 OPEN items get demoted to the overflow store
     when over budget; gauge shows a fill bar that shifts green→amber→red
     and yells JUMP! at 100%.
   - **Unbound** — no ceiling. The rope grows as needed (still tiny vs. the
     chat); nothing is ever demoted, zero recall risk; gauge shows absolute
     size with an ∞ instead of a fill bar.
3. Write the choice to `$JR/env` (mkdir -p + create if needed), preserving
   the other keys:
   ```
   JROPE_MODE=<bound|unbound>
   JROPE_BUDGET=<keep existing value, default 2000>
   JROPE_EMOJI=<keep existing value, default ➰>
   ```
   Keep the budget line even in unbound mode — it's reused when switching
   back to bound.
4. If a live rope exists and the user picked **bound** after running
   unbound, warn that the next `rope_ops.py log`/`jump` with the bound
   budget will demote over-budget detail to the overflow store (nothing is
   lost — it stays queryable via `rope_ops.py query`).
5. Confirm the new mode and what the gauge will now display. The statusline
   picks up the env on its next refresh — no restart needed.
