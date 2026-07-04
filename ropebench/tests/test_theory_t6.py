"""T6 — capability × density: a real model decodes what a literal reader can't.

T2's density "floor" is a *weak-reader* artifact. The rope carries a LEGEND that
defines every ai-native code; a model that reads it decodes the coded rope and
recovers the recall a literal substring-matcher loses. Measured: the scripted
reader drops ~10 pts on ai-native, live Haiku drops nothing (100% on both) — a
full capability recovery. Pins the committed live artifact so it can't rot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_ARTIFACT = (Path(__file__).resolve().parents[1]
             / "results" / "t6-capability-density" / "result.json")


def _load() -> dict:
    if not _ARTIFACT.exists():
        pytest.skip("T6 artifact absent (run research/exp_t6_capability_density.py)")
    return json.loads(_ARTIFACT.read_text())


def test_literal_reader_drops_but_capability_recovers() -> None:
    res = _load()
    scripted = res["scripted"]
    # the scripted literal reader pays the density tax on ai-native (T2).
    assert scripted["ai-native"] < scripted["symbolic-en"] - 0.05, scripted
    if "live" not in res:
        pytest.skip("live reader not in artifact")
    live = res["live"]
    # a real model reads the legend and decodes it — the ai-native drop vanishes.
    assert live["ai-native"] >= live["symbolic-en"] - 0.02, live
    # and it recovers strictly above the literal reader on the coded rope.
    assert live["ai-native"] > scripted["ai-native"] + 0.05, (live, scripted)
