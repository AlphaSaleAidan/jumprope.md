"""Render benchmark metrics as a markdown table and CSV."""

from __future__ import annotations

import csv
import io

from .runner import BUCKETS, KINDS, ProbeFilter, RegimeMetrics, paired

_ORDER = ("full-history", "truncate", "summary", "rope", "rope-unbound")
_TERCILES = ("early", "mid", "late")


def _ordered(metrics: dict[str, RegimeMetrics]) -> list[RegimeMetrics]:
    return [metrics[n] for n in _ORDER if n in metrics] + [
        m for n, m in metrics.items() if n not in _ORDER
    ]


def markdown(metrics: dict[str, RegimeMetrics]) -> str:
    lines = [
        "| Regime | Acc | short | medium | long | fact | decision | status "
        "| retrieval | tokens | acc/10k tok |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in _ordered(metrics):
        cells = [
            m.name,
            f"{m.accuracy():.0%}",
            *(f"{m.accuracy(bucket=b):.0%}" for b in BUCKETS),
            *(f"{m.accuracy(kind=k):.0%}" for k in KINDS),
            f"{m.retrieval_rate:.0%}",
            f"{m.total_tokens:,}",
            f"{m.efficiency:.1f}",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def paired_table(metrics: dict[str, RegimeMetrics], anchor: str = "rope") -> str:
    """Per condition-pair: n, point diff, 95% CI, verdict — anchored on the
    rope, so every claim in prose has a traceable CI (S1)."""
    if anchor not in metrics:
        return ""
    lines = [
        f"| {anchor} vs | n | {anchor} acc | other acc | diff | 95% CI | verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in _ORDER:
        if name == anchor or name not in metrics:
            continue
        r = paired(metrics[anchor], metrics[name])
        lines.append(
            f"| {name} | {r.n} | {r.mean_a:.0%} | {r.mean_b:.0%} | "
            f"{r.diff:+.1%} | [{r.ci_low:+.1%}, {r.ci_high:+.1%}] | "
            f"{r.verdict.replace('A-', anchor + '-')} |"
        )
    return "\n".join(lines)


def age_stratified_table(
    metrics: dict[str, RegimeMetrics], n_turns: int,
    condition: str = "summary", anchor: str = "rope",
) -> str:
    """Recall by fact-age tercile — the lead figure for 'summaries eat OLD
    facts'. Compares ``condition`` against ``anchor`` per tercile with CIs."""
    if condition not in metrics or anchor not in metrics:
        return ""
    lines = [
        f"| fact age | n | {condition} recall | {anchor} recall | diff | 95% CI |",
        "|---|---|---|---|---|---|",
    ]
    def in_tercile(tercile: str) -> ProbeFilter:
        return lambda p: p.age_tercile(n_turns) == tercile

    anchor_probes = [r.probe for r in metrics[anchor].probe_results]
    for tercile in _TERCILES:
        if not any(in_tercile(tercile)(p) for p in anchor_probes):
            continue  # this session introduced no facts in this tercile
        r = paired(metrics[condition], metrics[anchor], where=in_tercile(tercile))
        lines.append(
            f"| {tercile} | {r.n} | {r.mean_a:.0%} | {r.mean_b:.0%} | "
            f"{r.diff:+.1%} | [{r.ci_low:+.1%}, {r.ci_high:+.1%}] |"
        )
    return "\n".join(lines)


def report_card(
    metrics: dict[str, RegimeMetrics], model: str, seeds: list[int],
    n_turns: int, anchor: str = "rope",
) -> str:
    """Human-readable card: headline table + paired CIs + verdict sentences,
    generated from the numbers so prose can never drift from the data (S4)."""
    parts = [
        f"# RopeBench report card — {model}",
        f"\n_{len(seeds)} seed(s), {n_turns} turns, "
        f"{sum(len(m.probe_results) for m in metrics.values()) // max(1, len(metrics))} "
        "probes per condition._\n",
        "## Headline\n", markdown(metrics),
    ]
    if anchor in metrics:
        parts += ["\n## Paired comparison (95% CI)\n", paired_table(metrics, anchor)]
        parts.append("\n## Verdicts\n")
        for name in _ORDER:
            if name == anchor or name not in metrics:
                continue
            r = paired(metrics[anchor], metrics[name])
            parts.append(f"- {r.claim_phrase(anchor, name)}")
    if "summary" in metrics and anchor in metrics:
        parts += [
            "\n## Summarization by fact age (the lead finding)\n",
            age_stratified_table(metrics, n_turns),
        ]
    return "\n".join(parts) + "\n"


def report_json(
    metrics: dict[str, RegimeMetrics], model: str, seeds: list[int], n_turns: int,
) -> dict[str, object]:
    """Machine-readable raw numbers — what a third party posts to prove a
    reproduction (S4). Every point estimate, paired CI and verdict."""
    conditions = {
        name: {
            "accuracy": round(m.accuracy(), 4),
            "total_tokens": m.total_tokens,
            "efficiency": round(m.efficiency, 3),
            "retrieval_rate": round(m.retrieval_rate, 4),
            "n_probes": len(m.probe_results),
        }
        for name, m in metrics.items()
    }
    pairs = {}
    if "rope" in metrics:
        for name, m in metrics.items():
            if name == "rope":
                continue
            r = paired(metrics["rope"], m)
            pairs[f"rope_vs_{name}"] = {
                "n": r.n, "diff": round(r.diff, 4),
                "ci_low": round(r.ci_low, 4), "ci_high": round(r.ci_high, 4),
                "verdict": r.verdict, "wins": r.wins, "losses": r.losses,
            }
    return {
        "model": model, "seeds": seeds, "n_turns": n_turns,
        "conditions": conditions, "paired": pairs,
    }


def csv_rows(metrics: dict[str, RegimeMetrics]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["regime", "probe_tag", "kind", "bucket", "distance", "hit",
         "used_retrieval", "answer"]
    )
    for m in _ordered(metrics):
        for r in m.probe_results:
            writer.writerow(
                [m.name, r.probe.tag, r.probe.kind, r.probe.bucket,
                 r.probe.distance, int(r.hit), int(r.used_retrieval),
                 r.answer[:120]]
            )
    return buffer.getvalue()
