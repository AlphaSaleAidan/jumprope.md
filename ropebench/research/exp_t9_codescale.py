"""T9 — code-scale retrieval: does the rope+vault pattern hold on a REAL, large
codebase full of near-duplicate symbols?

T7 proved exact addressing beats semantic search under synthetic near-duplicates.
Real code is the natural habitat of that problem: a big codebase has hundreds of
`close`, `read`, `run`, `__init__` methods, near-identical signatures everywhere.
This runs the same contest on the actual Python 3.12 standard library
(~875k lines, ~60k defs) — no synthetic data.

Part A (scripted, FREE): for a target function whose *name* is shared by N other
real functions, can semantic search return THE RIGHT one? vs an exact
content-addressed fetch (the rope's KEYS handle: file::symbol). As N grows,
semantic must pick the target out of N near-duplicates.

Part B (bounded live, opt-in via --live): pack real code to ~80k tokens, hide one
distinctive target at depth 10/50/90%, ask a live model to recall it — does
lost-in-the-middle bite at code scale (where 150k LOC fits in nothing)?

Usage:
    python exp_t9_codescale.py            # Part A only (free)
    python exp_t9_codescale.py --live     # + Part B live LITM probe
"""

from __future__ import annotations

import ast
import shlex
import statistics
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from jumping_rope.tokens import count_tokens
from jumping_rope.turbovec import TurboVec

CODE_ROOT = Path("/usr/lib/python3.12")


@dataclass
class Func:
    file: str
    name: str
    lineno: int
    source: str


def collect_funcs(root: Path, max_files: int = 600, max_src_lines: int = 25) -> list[Func]:
    """Parse .py files and pull out function defs with their source snippet."""
    funcs: list[Func] = []
    files = sorted(root.rglob("*.py"))[:max_files]
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text)
        except (SyntaxError, ValueError, OSError):
            continue
        lines = text.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                end = min(node.lineno + max_src_lines, node.end_lineno or node.lineno)
                src = "\n".join(lines[node.lineno - 1:end])
                if len(src) > 40:  # skip trivial stubs
                    funcs.append(Func(file=str(path.relative_to(root)),
                                      name=node.name, lineno=node.lineno, source=src))
    return funcs


def _by_name(funcs: list[Func]) -> dict[str, list[Func]]:
    out: dict[str, list[Func]] = {}
    for f in funcs:
        out.setdefault(f.name, []).append(f)
    return out


def part_a(funcs: list[Func], distractor_counts=(0, 2, 4, 8, 16, 32),
           n_targets: int = 60, k: int = 3) -> dict[int, dict[str, float]]:
    """For each N: put target + N same-named real functions in a vault; can
    semantic search (query = the function's name) return the exact target?
    vs an exact content-addressed fetch."""
    by_name = _by_name(funcs)
    # distinct-file variants per name (genuine near-duplicates)
    variants_by_name: dict[str, list[Func]] = {}
    for name, group in by_name.items():
        if name.startswith("__"):
            continue
        seen_files: set[str] = set()
        vs: list[Func] = []
        for f in group:
            if f.file not in seen_files:
                seen_files.add(f.file)
                vs.append(f)
        if len(vs) >= 2:
            variants_by_name[name] = vs
    out: dict[int, dict[str, float]] = {}
    for n in distractor_counts:
        flat_hits, rope_hits = [], []
        # per-N: any name with at least n+1 distinct-file versions qualifies
        eligible = sorted(name for name, vs in variants_by_name.items()
                          if len(vs) >= n + 1)[:n_targets]
        for name in eligible:
            variants = variants_by_name[name]
            target = variants[0]
            db = Path(tempfile.mkdtemp(prefix="t9-")) / "v.db"
            vault = TurboVec(db, force_fallback=True)
            target_key = vault.put(session_id="t9", jump_index=0, section="CODE",
                                   content=target.source, turn=0)
            for d in variants[1:n + 1]:
                vault.put(session_id="t9", jump_index=0, section="CODE",
                          content=d.source, turn=1)
            # semantic: you only remember the symbol name, not which file
            hits = vault.search(f"def {name}", k=k, session_id="t9")
            flat_hits.append(int(any(h.key == target_key for h in hits)))
            # rope: exact KEYS handle → content-addressed fetch
            rec = vault.get(target_key)
            rope_hits.append(int(rec is not None and rec.key == target_key))
            vault.close()
        out[n] = {"flat": statistics.mean(flat_hits) if flat_hits else 0.0,
                  "rope": statistics.mean(rope_hits) if rope_hits else 0.0,
                  "n_targets": len(flat_hits), "chance": min(1.0, k / (n + 1))}
    return out


def part_b_live(funcs: list[Func], cmd: str, target_tokens: int = 80_000,
                depths=(0.1, 0.5, 0.9), n_targets: int = 4) -> dict:
    """Pack real code to ~target_tokens, hide one distinctive target at each
    depth, ask a live model to recall it. Tests LITM at code scale."""
    argv = shlex.split(cmd)
    # a big pile of real function sources as the "carried codebase"
    pile = [f.source for f in funcs]
    rows = []
    for depth in depths:
        hits = 0
        for t in range(n_targets):
            marker = f"ZK{7000 + t}Q"  # distinctive, unguessable token
            target = (f"def config_checkpoint_{t}():\n"
                      f"    # canary marker for recall\n"
                      f"    return '{marker}'  # pinned build id")
            body, toks = [], 0
            for src in pile:
                if toks >= target_tokens:
                    break
                body.append(src)
                toks += count_tokens(src)
            pos = min(len(body) - 1, max(0, round(depth * (len(body) - 1))))
            body.insert(pos, target)
            context = "\n\n".join(body)
            q = (f"In the code above there is a function config_checkpoint_{t} that "
                 f"returns a single quoted token. Reply with ONLY that exact token.")
            prompt = (f"You answer recall questions about a large codebase. Reply "
                      f"with ONLY the exact token.\n\nCODE:\n{context}\n\nQUESTION: {q}")
            try:
                proc = subprocess.run(argv, input=prompt, capture_output=True,
                                      text=True, timeout=180, check=False)
                ans = proc.stdout.strip()
            except subprocess.TimeoutExpired:
                ans = ""
            hit = marker in ans
            hits += int(hit)
            rows.append({"depth": depth, "ctx_tokens": count_tokens(context),
                         "marker": marker, "hit": int(hit), "answer": ans[:60]})
        print(f"  depth={depth:>4} : {hits}/{n_targets}", flush=True)
    return {"cmd": cmd, "target_tokens": target_tokens, "rows": rows}


if __name__ == "__main__":
    live = "--live" in sys.argv
    print(f"collecting functions from {CODE_ROOT} ...", flush=True)
    funcs = collect_funcs(CODE_ROOT)
    total_tokens = sum(count_tokens(f.source) for f in funcs)
    print(f"collected {len(funcs)} funcs (~{total_tokens:,} tokens of code); "
          f"a codebase this size does NOT fit any context window.\n", flush=True)

    print("=== Part A: exact-key vs semantic recall on REAL near-duplicate code ===",
          flush=True)
    res = part_a(funcs)
    print(f"{'N same-named':>12} | {'flat semantic':>13} | {'rope exact':>10} "
          f"| {'chance':>7} | targets", flush=True)
    for n, row in res.items():
        print(f"{n:>12} | {row['flat']:>12.0%} | {row['rope']:>9.0%} | "
              f"{row['chance']:>6.0%} | {row['n_targets']}", flush=True)

    out_dir = Path(__file__).resolve().parents[1] / "results" / "t9-codescale"
    out_dir.mkdir(parents=True, exist_ok=True)
    import json
    payload = {"code_root": str(CODE_ROOT), "n_funcs": len(funcs),
               "code_tokens": total_tokens, "part_a": res}

    if live:
        print("\n=== Part B: lost-in-the-middle at ~80k tokens of REAL code ===",
              flush=True)
        cmd = "claude -p --model haiku"
        payload["part_b"] = part_b_live(funcs, cmd)

    (out_dir / "result.json").write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nwrote {out_dir / 'result.json'}", flush=True)
