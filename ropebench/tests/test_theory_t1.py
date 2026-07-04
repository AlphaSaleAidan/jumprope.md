"""T1 — the memory hierarchy's value grows with session length.

Full-history cost grows super-linearly (every turn pays for all prior turns);
the rope stays bounded, so its efficiency advantage widens as sessions get
longer. This is the quantitative backbone of 'past a point there is no
carry-everything'.
"""

from __future__ import annotations

import math

from ropebench.runner import run_benchmark


def test_rope_advantage_grows_with_session_length() -> None:
    lengths = [40, 120, 200]
    full_tok, rope_tok, eff_ratio = [], [], []
    for n in lengths:
        m = run_benchmark(seeds=[1, 2], n_turns=n)
        full_tok.append(m["full-history"].total_tokens)
        rope_tok.append(m["rope"].total_tokens)
        eff_ratio.append(m["rope"].efficiency / m["full-history"].efficiency)

    # full/rope token ratio strictly increases with length.
    ratios = [f / r for f, r in zip(full_tok, rope_tok, strict=True)]
    assert ratios[0] < ratios[1] < ratios[2], ratios
    # the rope's efficiency advantage strictly increases too.
    assert eff_ratio[0] < eff_ratio[1] < eff_ratio[2], eff_ratio

    # full-history grows super-linearly; the rope sub-linearly (log-log slope).
    def slope(xs: list[int], ys: list[int]) -> float:
        lx = [math.log(x) for x in xs]
        ly = [math.log(y) for y in ys]
        n = len(xs)
        mx, my = sum(lx) / n, sum(ly) / n
        return sum((a - mx) * (b - my) for a, b in zip(lx, ly, strict=True)) / sum(
            (a - mx) ** 2 for a in lx
        )

    assert slope(lengths, full_tok) > 1.15, "full-history should grow super-linearly"
    assert slope(lengths, rope_tok) < slope(lengths, full_tok)
