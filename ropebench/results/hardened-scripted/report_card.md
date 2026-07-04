# RopeBench report card — scripted

_5 seed(s), 80 turns, 150 probes per condition._

## Headline

| Regime | Acc | short | medium | long | fact | decision | status | retrieval | tokens | acc/10k tok |
|---|---|---|---|---|---|---|---|---|---|---|
| full-history | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 0% | 511,489 | 2.0 |
| truncate | 86% | 100% | 100% | 48% | 84% | 88% | 90% | 0% | 354,756 | 2.4 |
| summary | 71% | 100% | 89% | 5% | 71% | 68% | 73% | 0% | 335,994 | 2.1 |
| rope | 93% | 98% | 85% | 98% | 100% | 75% | 100% | 53% | 255,381 | 3.7 |
| rope-unbound | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 0% | 898,294 | 1.1 |

## Paired comparison (95% CI)

| rope vs | n | rope acc | other acc | diff | 95% CI | verdict |
|---|---|---|---|---|---|---|
| full-history | 150 | 93% | 100% | -6.7% | [-10.7%, -2.7%] | rope-worse |
| truncate | 150 | 93% | 86% | +7.3% | [+0.7%, +14.7%] | rope-better |
| summary | 150 | 93% | 71% | +22.7% | [+14.7%, +30.7%] | rope-better |
| rope-unbound | 150 | 93% | 100% | -6.7% | [-10.7%, -2.7%] | rope-worse |

## Verdicts

- rope trails full-history (93% vs 100%; 95% CI [-10.7%, -2.7%], n=150)
- rope beats truncate (93% vs 86%; 95% CI [+0.7%, +14.7%], n=150)
- rope beats summary (93% vs 71%; 95% CI [+14.7%, +30.7%], n=150)
- rope trails rope-unbound (93% vs 100%; 95% CI [-10.7%, -2.7%], n=150)

## Summarization by fact age (the lead finding)

| fact age | n | summary recall | rope recall | diff | 95% CI |
|---|---|---|---|---|---|
| early | 65 | 74% | 94% | -20.0% | [-32.3%, -7.7%] |
| mid | 70 | 61% | 91% | -30.0% | [-42.9%, -17.1%] |
| late | 15 | 100% | 100% | +0.0% | [+0.0%, +0.0%] |
