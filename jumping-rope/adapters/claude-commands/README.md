# /jumprope-* — Claude Code slash commands

Four slash commands that make the rope a first-class citizen of a Claude Code
session, pairing with the [statusline gauge](../claude-statusline/):

| command | does |
|---|---|
| `/jumprope-start` | create THIS session's rope and seed it from live session state — the gauge comes alive |
| `/jumprope-cut` | archive the session's rope (never deletes) — gauge returns to "no rope" |
| `/jumprope-mode` | pick **bound** (hard cap, fill bar, JUMP! at 100%) or **unbound** (∞, nothing demoted) via an interactive picker |
| `/jumprope-status` | is the rope running + a ~1s live self-test: write → budget-forced demotion → retrieval → jump |

## Per-session ropes

Each Claude Code session gets its own rope at

```
<project>/.claude/jumprope/sessions/<session_id>/
    ROPE.md            the rope
    env                KEY=VALUE config (JROPE_MODE, JROPE_BUDGET, JROPE_EMOJI)
    .rope_overflow.md  demoted detail (degraded mode) — or .jrope/ with the package
```

The commands key the path off `$CLAUDE_CODE_SESSION_ID`; the statusline
adapter keys off the `session_id` Claude Code pipes to it. Concurrent
sessions in the same repo never fight over one rope file, and each gauge
shows only its own session. Add `.claude/jumprope/` to the project's
`.gitignore`.

## Install

1. Copy the four `jumprope-*.md` files into the project's
   `.claude/commands/`.
2. Replace `/ABS/PATH/jumprope.md` in them with wherever this repo is
   cloned (the commands drive the skill's `rope_ops.py`, which works with or
   without the `jumping-rope` package installed — degraded mode keeps the
   same file format).
3. Wire up the [statusline gauge](../claude-statusline/README.md) so the
   rope is visible while it runs.
