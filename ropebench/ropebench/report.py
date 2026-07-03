"""Render benchmark metrics as a markdown table and CSV."""

from __future__ import annotations

import csv
import io

from .runner import BUCKETS, KINDS, RegimeMetrics

_ORDER = ("full-history", "truncate", "summary", "rope", "rope-unbound")


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
