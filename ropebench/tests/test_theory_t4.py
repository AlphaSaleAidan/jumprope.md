"""T4 — retrieval compensates: the rope's efficiency is maximized at the
TIGHTEST satisfiable budget, not a large one.

A smaller resident rope forces more demotion → higher retrieval → the vault
carries the load, so accuracy stays high while tokens stay low. Efficiency
(accuracy per 10k tokens) therefore falls monotonically as the budget grows.
"""

from __future__ import annotations

import tempfile

from jumping_rope import JumpConfig

from ropebench.models import ScriptedModel
from ropebench.regimes import RopeRegime
from ropebench.runner import run_scenario
from ropebench.scenario import generate


def _sweep(budget: int) -> tuple[float, float, float]:
    accs: list[float] = []
    effs: list[float] = []
    retrs: list[float] = []
    model = ScriptedModel()
    for seed in (1, 2):
        r = RopeRegime(
            data_dir=tempfile.mkdtemp(),
            config=JumpConfig(rope_budget_tokens=budget,
                              jump_threshold_tokens=budget * 3, jump_every_n_turns=8),
        )
        m = run_scenario(generate(seed, n_turns=80), [r], model)["rope"]
        accs.append(m.accuracy())
        effs.append(m.efficiency)
        retrs.append(m.retrieval_rate)
    return sum(accs) / 2, sum(effs) / 2, sum(retrs) / 2


def test_efficiency_falls_as_budget_grows() -> None:
    tight_acc, tight_eff, tight_retr = _sweep(400)
    wide_acc, wide_eff, wide_retr = _sweep(3000)
    # tight budget: much better efficiency, more retrieval.
    assert tight_eff > 2 * wide_eff, (tight_eff, wide_eff)
    assert tight_retr > wide_retr
    # and accuracy stays high at the tight budget (retrieval compensates).
    assert tight_acc >= 0.90
