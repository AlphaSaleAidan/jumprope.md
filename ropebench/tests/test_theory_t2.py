"""T2 — density has a floor: past a point, compression hurts recall.

Values survive densification verbatim, but the aggressive ai-native dictionary
codes away the *context words* a literal reader matches the question against, so
its recall drops vs the lighter symbolic-en. Density is not free for weak
readers (a capable model that decodes via the legend recovers it — see T6).
"""

from __future__ import annotations

import tempfile

from jumping_rope import JumpConfig

from ropebench.models import ScriptedModel
from ropebench.regimes import RopeRegime
from ropebench.runner import run_scenario
from ropebench.scenario import generate


def _acc(profile: str) -> float:
    accs = []
    model = ScriptedModel()
    for seed in (1, 2, 3):
        r = RopeRegime(
            data_dir=tempfile.mkdtemp(),
            config=JumpConfig(rope_budget_tokens=600, jump_threshold_tokens=1800,
                              jump_every_n_turns=8, notation_profile=profile),
        )
        m = run_scenario(generate(seed, n_turns=80), [r], model)["rope"]
        accs.append(m.accuracy())
    return sum(accs) / len(accs)


def test_aggressive_dictionary_coding_lowers_literal_reader_recall() -> None:
    symbolic = _acc("symbolic-en")
    ai_native = _acc("ai-native")
    # ai-native trades matchability for density → measurably worse for a
    # literal reader (the density floor).
    assert ai_native < symbolic - 0.05, (ai_native, symbolic)
