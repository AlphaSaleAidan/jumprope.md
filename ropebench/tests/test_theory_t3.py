"""T3 — structure beats a flat dense blob, and the gap is in OLD facts.

Same budget, same densification, same retrieval vault — the only difference is
structure: the rope's never-demoted STATE/GOALS + the KEYS index give old facts
a durable home and a findable pointer, while a flat blob drops old lines into
semantic-search-only limbo. Result: structure wins decisively at long distance.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from jumping_rope import JumpConfig
from jumping_rope.notation import get_profile
from jumping_rope.tokens import count_tokens
from jumping_rope.turbovec import TurboVec, format_retrieved

from ropebench.models import ScriptedModel
from ropebench.regimes import RegimeBase, RetrieveFn, RopeRegime
from ropebench.runner import run_scenario
from ropebench.scenario import Event, generate


class FlatDenseRegime(RegimeBase):
    """Densified events in a flat blob, drop-oldest to a vault, retrieval on —
    the rope minus its structure."""

    name = "flat-dense"

    def __init__(self, budget: int = 600) -> None:
        super().__init__()
        self.budget = budget
        self.lines: list[str] = []
        self._prof = get_profile("symbolic-en")
        self._vault = TurboVec(Path(tempfile.mkdtemp()) / "v.db", force_fallback=True)

    def observe(self, turn: int, events: list[Event]) -> None:
        for e in events:
            self.lines.append(self._prof.densify(e.text))
        while count_tokens("\n".join(self.lines)) > self.budget and len(self.lines) > 1:
            old = self.lines.pop(0)
            self._vault.put(session_id="fd", jump_index=0, section="X", content=old)

    def context(self) -> str:
        return "\n".join(self.lines)

    def retriever(self) -> RetrieveFn:
        def r(q: str) -> str:
            hits = self._vault.search(q, k=3)
            return "\n".join(format_retrieved(h.key, h.content) for h in hits)
        return r

    def close(self) -> None:
        self._vault.close()


def _long_acc(factory: object, name: str) -> float:
    accs = []
    model = ScriptedModel()
    for seed in (1, 2, 3):
        m = run_scenario(generate(seed, n_turns=80), [factory()], model)[name]  # type: ignore[operator]
        accs.append(m.accuracy(bucket="long"))
    return sum(accs) / len(accs)


def test_structure_wins_at_long_distance() -> None:
    rope_long = _long_acc(
        lambda: RopeRegime(
            data_dir=tempfile.mkdtemp(),
            config=JumpConfig(rope_budget_tokens=600, jump_threshold_tokens=1800,
                              jump_every_n_turns=8)),
        "rope",
    )
    flat_long = _long_acc(lambda: FlatDenseRegime(600), "flat-dense")
    # Structure's advantage is concentrated in old facts — a large gap.
    assert rope_long > flat_long + 0.20, (rope_long, flat_long)
