"""RopeBench: effectiveness benchmark for LLM context-handoff strategies.

Measures a context-management POLICY with the model held constant: the same
synthetic session stream is replayed through four regimes (full history,
truncate-oldest, summary compaction, Jumping Rope) and scored on state
continuity — fact retention by distance, decision recall, goal status — and
on token cost. Scripted mode is deterministic and network-free (information
availability); live mode swaps in a real model (information use).
"""

from .models import ModelAnswer, OpenAICompatModel, ScriptedModel
from .regimes import (
    FullHistoryRegime,
    RegimeBase,
    RopeRegime,
    RopeUnboundRegime,
    SummaryRegime,
    TruncateRegime,
    default_regimes,
)
from .report import csv_rows, markdown
from .runner import RegimeMetrics, run_benchmark, run_scenario
from .scenario import Event, Probe, Scenario, generate

__version__ = "0.1.0"

__all__ = [
    "Event",
    "FullHistoryRegime",
    "ModelAnswer",
    "OpenAICompatModel",
    "Probe",
    "RegimeBase",
    "RegimeMetrics",
    "RopeRegime",
    "RopeUnboundRegime",
    "Scenario",
    "ScriptedModel",
    "SummaryRegime",
    "TruncateRegime",
    "__version__",
    "csv_rows",
    "default_regimes",
    "generate",
    "markdown",
    "run_benchmark",
    "run_scenario",
]
