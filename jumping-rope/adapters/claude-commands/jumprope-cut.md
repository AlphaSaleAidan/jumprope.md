---
name: jumprope-cut
description: Cut THIS session's Jumping Rope — archive its ROPE.md and return the statusline gauge to "no rope".
---

# /jumprope-cut — end the rope for this session

Steps (this session's rope only — other sessions' ropes are untouched):

```bash
JR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/jumprope/sessions/${CLAUDE_CODE_SESSION_ID:-default}"
```

1. If `$JR/ROPE.md` does not exist, tell the user there is no live rope for
   this session and stop.
2. Give the user a one/two-sentence parting summary of what the rope carried
   (read `$JR/ROPE.md`; only show the raw rope if it is short).
3. Archive, never delete outright:
   ```bash
   ts=$(date -u +%Y%m%dT%H%M%SZ)
   ARC="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/jumprope/archive/${CLAUDE_CODE_SESSION_ID:-default}-$ts"
   mkdir -p "$ARC"
   mv "$JR/ROPE.md" "$ARC/"
   [ -f "$JR/.rope_overflow.md" ] && mv "$JR/.rope_overflow.md" "$ARC/"
   [ -d "$JR/.jrope" ] && mv "$JR/.jrope" "$ARC/"
   ```
   Keep `$JR/env` in place — mode/budget/emoji survive for a restart.
4. Confirm: rope cut and archived to `$ARC`; the statusline gauge will read
   "no rope — /jumprope-start" on its next refresh.
5. Stop logging to the rope for the remainder of the session (until a new
   /jumprope-start).
