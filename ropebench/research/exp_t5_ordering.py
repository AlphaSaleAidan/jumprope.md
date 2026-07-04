"""T5 — does position in the context change a live model's recall?

The scripted reader scans every line by overlap, so it is position-invariant by
construction — T5 can only be measured with a *live* model. Hypothesis (the
"lost in the middle" effect): a fact buried in the MIDDLE of a large carried
context is recalled worse than the same fact near the edges; a small context has
no deep middle to get lost in, so it is position-robust.

If true, this is another reason tight budgets win (T4): the rope's small
resident set sidesteps a failure mode that carry-everything walks into.

Runs a bounded, FREE sweep against a local CLI model (`claude -p --model haiku`
by default — no Meridian, no paid API). Writes results/t5-ordering/result.json.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

from jumping_rope.tokens import count_tokens

SYSTEM = ("You are answering a recall question from CONTEXT. Reply with ONLY the "
          "exact token requested — no sentence, no explanation.")
_ADJ = ["amber", "brisk", "coral", "dusky", "ember", "frosted", "gilded", "hollow",
        "ionic", "jasper", "kelp", "lunar"]
_NOUN = ["anchor", "baffle", "crank", "dynamo", "eyelet", "flange", "gasket",
         "hinge", "impeller", "jig", "keel", "lattice"]
_FILL_V = ["renamed", "reordered", "tidied", "reindented", "annotated", "linted"]
_FILL_O = ["helper utilities", "import blocks", "test fixtures", "log strings",
           "type hints", "shell scripts"]


def _filler(i: int) -> str:
    return (f"routine change {i}: {_FILL_V[i % 6]} the {_FILL_O[(i * 5) % 6]} "
            f"across the module, no functional effect")


def _context(target: str, depth: float, n_lines: int) -> str:
    """n_lines of filler with the target inserted at fractional depth."""
    lines = [_filler(i) for i in range(n_lines)]
    pos = min(n_lines - 1, max(0, round(depth * (n_lines - 1))))
    lines.insert(pos, target)
    return "\n".join(lines)


def _ask(argv: list[str], context: str, question: str, timeout_s: int = 90) -> str:
    prompt = f"{SYSTEM}\n\nCONTEXT:\n{context}\n\nQUESTION: {question}"
    try:
        proc = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                              timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return ""
    return proc.stdout.strip()


def run(cmd: str = "claude -p --model haiku", n_targets: int = 8,
        depths: tuple[float, ...] = (0.05, 0.5, 0.95),
        sizes: tuple[tuple[str, int], ...] = (
            ("small", 30), ("large", 320), ("xlarge", 1200))) -> dict:
    argv = shlex.split(cmd)
    rows: list[dict] = []
    for size_name, n_lines in sizes:
        for depth in depths:
            hits = 0
            for t in range(n_targets):
                adj, noun = _ADJ[t], _NOUN[t]
                value = f"argon-{1000 + t}"
                target = (f"the {adj} {noun} pipeline is pinned to build {value} "
                          f"until further notice")
                ctx = _context(target, depth, n_lines)
                q = (f"What build is the {adj} {noun} pipeline pinned to? "
                     f"Answer with the exact token.")
                ans = _ask(argv, ctx, q)
                hit = value in ans.lower()
                hits += int(hit)
                rows.append({"size": size_name, "n_lines": n_lines, "depth": depth,
                             "ctx_tokens": count_tokens(ctx), "target": value,
                             "hit": int(hit), "answer": ans[:80]})
            print(f"  {size_name:>5} depth={depth:>4} : {hits}/{n_targets}", flush=True)
    return {"cmd": cmd, "n_targets": n_targets, "rows": rows}


def summarize(result: dict) -> str:
    rows = result["rows"]
    sizes = sorted({r["size"] for r in rows}, key=lambda s: 0 if s == "small" else 1)
    depths = sorted({r["depth"] for r in rows})
    out = ["| size (ctx tok) | " + " | ".join(f"depth {d:.0%}" for d in depths) + " |",
           "|---|" + "---|" * len(depths)]
    for size in sizes:
        srows = [r for r in rows if r["size"] == size]
        toks = round(sum(r["ctx_tokens"] for r in srows) / len(srows))
        cells = []
        for d in depths:
            drows = [r for r in srows if r["depth"] == d]
            acc = sum(r["hit"] for r in drows) / len(drows)
            cells.append(f"{acc:.0%}")
        out.append(f"| {size} (~{toks}) | " + " | ".join(cells) + " |")
    return "\n".join(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "claude -p --model haiku"
    print(f"T5 ordering sweep via: {cmd}", flush=True)
    res = run(cmd=cmd)
    out_dir = Path(__file__).resolve().parents[1] / "results" / "t5-ordering"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(res, indent=2))
    table = summarize(res)
    (out_dir / "table.md").write_text(table + "\n")
    print("\n" + table, flush=True)
