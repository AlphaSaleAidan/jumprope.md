"""T6 — capability × density: does a real model decode what a literal reader can't?

T2 showed aggressive ai-native dictionary coding drops the *scripted literal
reader's* recall (it codes away the context words a keyword-matcher aligns the
question against). The T6 question: a rope carries a LEGEND that defines every
code — a model that *reads the legend* should decode the ai-native rope and
recover the lost recall, where a literal substring-matcher can't.

If capability recovers the density loss, then ai-native is "safe" for real
deployments and T2's floor is a weak-reader artifact. This is the capability
gradient: scripted (zero decoding) → live model (decodes via legend).

Runs the SAME ropes (symbolic-en vs ai-native) under two readers: the scripted
literal matcher (free) and a live CLI model (`claude -p --model haiku`, no
Meridian). Bounded and free-ish.
"""

from __future__ import annotations

import json
import shlex
import statistics
import sys
import tempfile
from pathlib import Path

from jumping_rope import JumpConfig

from ropebench.models import CommandModel, Model, ScriptedModel
from ropebench.regimes import RopeRegime
from ropebench.runner import run_scenario
from ropebench.scenario import generate

PROFILES = ("symbolic-en", "ai-native")


def _rope_accuracy(model: Model, profile: str, seed: int, n_turns: int = 80) -> float:
    regime = RopeRegime(
        data_dir=tempfile.mkdtemp(prefix=f"t6-{profile}-"),
        config=JumpConfig(rope_budget_tokens=600, jump_threshold_tokens=1800,
                          jump_every_n_turns=8, notation_profile=profile),
    )
    metrics = run_scenario(generate(seed, n_turns=n_turns), [regime], model)["rope"]
    return metrics.accuracy()


def run(cmd: str | None, seeds: tuple[int, ...] = (1, 2)) -> dict:
    readers: dict[str, Model] = {"scripted": ScriptedModel()}
    if cmd:
        readers["live"] = CommandModel(argv=shlex.split(cmd))
    out: dict[str, dict[str, float]] = {}
    for reader_name, model in readers.items():
        for profile in PROFILES:
            accs = []
            for seed in seeds:
                accs.append(_rope_accuracy(model, profile, seed))
                print(f"  {reader_name:>8} · {profile:>11} · seed {seed}: "
                      f"{accs[-1]:.0%}", flush=True)
            out.setdefault(reader_name, {})[profile] = statistics.mean(accs)
    return out


def summarize(res: dict) -> str:
    lines = ["| reader | symbolic-en | ai-native | ai-native drop |",
             "|---|---|---|---|"]
    for reader, row in res.items():
        s, a = row["symbolic-en"], row["ai-native"]
        lines.append(f"| {reader} | {s:.0%} | {a:.0%} | {a-s:+.0%} |")
    if "scripted" in res and "live" in res:
        recovered = res["live"]["ai-native"] - res["scripted"]["ai-native"]
        lines.append(f"\ncapability recovery on ai-native (live − scripted): "
                     f"{recovered:+.0%}")
    return "\n".join(lines)


if __name__ == "__main__":
    cmd = None if "--scripted-only" in sys.argv else "claude -p --model haiku"
    print(f"T6 capability × density (reader = scripted{' + live ' + cmd if cmd else ''})",
          flush=True)
    res = run(cmd)
    out_dir = Path(__file__).resolve().parents[1] / "results" / "t6-capability-density"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(res, indent=2))
    table = summarize(res)
    (out_dir / "table.md").write_text(table + "\n")
    print("\n" + table, flush=True)
