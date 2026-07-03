"""Paired benchmark runner: same scenario stream, four context regimes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from jumping_rope.tokens import count_tokens

from .models import Model, ModelAnswer, ScriptedModel
from .regimes import RegimeBase, default_regimes
from .scenario import LONG, MEDIUM, SHORT, Probe, Scenario, generate


@dataclass
class ProbeResult:
    probe: Probe
    answer: str
    hit: bool
    used_retrieval: bool


@dataclass
class RegimeMetrics:
    name: str
    probe_results: list[ProbeResult] = field(default_factory=list)
    context_tokens: int = 0  # per-turn context cost, summed
    probe_tokens: int = 0  # context+question+retrieval tokens at probes

    @property
    def total_tokens(self) -> int:
        return self.context_tokens + self.probe_tokens

    def accuracy(self, kind: str | None = None, bucket: str | None = None) -> float:
        results = [
            r
            for r in self.probe_results
            if (kind is None or r.probe.kind == kind)
            and (bucket is None or r.probe.bucket == bucket)
        ]
        if not results:
            return 0.0
        return sum(r.hit for r in results) / len(results)

    @property
    def retrieval_rate(self) -> float:
        if not self.probe_results:
            return 0.0
        return sum(r.used_retrieval for r in self.probe_results) / len(self.probe_results)

    @property
    def efficiency(self) -> float:
        """Accuracy points per 10k tokens spent — the Pareto number."""
        if self.total_tokens == 0:
            return 0.0
        return 100 * self.accuracy() / (self.total_tokens / 10_000)


AnswerFn = Callable[[str, str, object], ModelAnswer]


def _score(probe: Probe, answer: str) -> bool:
    lowered = answer.lower()
    return any(expected.lower() in lowered for expected in probe.expected_any)


def run_scenario(
    scenario: Scenario,
    regimes: list[RegimeBase],
    model: Model,
) -> dict[str, RegimeMetrics]:
    metrics = {r.name: RegimeMetrics(name=r.name) for r in regimes}
    for turn in range(1, scenario.n_turns + 1):
        events = scenario.turns[turn - 1]
        for regime in regimes:
            regime.observe(turn, events)
            regime.end_turn()
        for probe in scenario.probes_at(turn):
            for regime in regimes:
                context = regime.context()
                result: ModelAnswer = model.answer(
                    context, probe.question, regime.retriever()
                )
                m = metrics[regime.name]
                m.probe_tokens += (
                    count_tokens(context)
                    + count_tokens(probe.question)
                    + result.extra_tokens
                )
                m.probe_results.append(
                    ProbeResult(
                        probe=probe,
                        answer=result.text,
                        hit=_score(probe, result.text),
                        used_retrieval=result.used_retrieval,
                    )
                )
    for regime in regimes:
        metrics[regime.name].context_tokens = regime.total_tokens
        regime.close()
    return metrics


def merge(runs: list[dict[str, RegimeMetrics]]) -> dict[str, RegimeMetrics]:
    merged: dict[str, RegimeMetrics] = {}
    for run in runs:
        for name, m in run.items():
            agg = merged.setdefault(name, RegimeMetrics(name=name))
            agg.probe_results.extend(m.probe_results)
            agg.context_tokens += m.context_tokens
            agg.probe_tokens += m.probe_tokens
    return merged


def run_benchmark(
    seeds: list[int],
    n_turns: int = 80,
    model: Model | None = None,
    regime_factory: Callable[[], list[RegimeBase]] = default_regimes,
) -> dict[str, RegimeMetrics]:
    active_model: Model = model if model is not None else ScriptedModel()
    runs = []
    for seed in seeds:
        scenario = generate(seed, n_turns=n_turns)
        runs.append(run_scenario(scenario, regime_factory(), active_model))
    return merge(runs)


BUCKETS = (SHORT, MEDIUM, LONG)
KINDS = ("fact", "decision", "status")
