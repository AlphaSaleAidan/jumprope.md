# Skill provenance

- `ponytail*` — vendored from [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) (MIT).
  Minimal-code discipline for every agent writing rope-creation/storage code
  in this repo: simplest solution that works, stdlib before dependencies,
  one line before fifty.
- `jumping-rope/` — this project's own skill (canonical source:
  `jumping-rope/adapters/claude-skill/jumping-rope/`). Makes the agent
  maintain ROPE.md continuously and re-seed from it after context clears.
