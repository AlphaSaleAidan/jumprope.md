"""§8.9 — Claude-skill rope_ops.py in installed AND degraded modes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from jumping_rope.rope import RopeFile

_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "adapters"
    / "claude-skill"
    / "jumping-rope"
    / "scripts"
    / "rope_ops.py"
)


def run_ops(
    args: list[str], cwd: Path, degraded: bool
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if degraded:
        env["JROPE_FORCE_DEGRADED"] = "1"
    else:
        env.pop("JROPE_FORCE_DEGRADED", None)
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def drive_workflow(root: Path, degraded: bool) -> str:
    """init → log all sections → jump → query; return final rope text."""
    result = run_ops(["init"], root, degraded)
    assert result.returncode == 0, result.stderr
    for args in (
        ["log", "state", "/srv/skill", "--key", "cwd"],
        ["log", "goal", "prove both modes", "--status", "active"],
        ["log", "decision", "keyring bundling for KEYS overflow", "--reason", "bounded rope"],
        ["log", "delta", "added degraded mode", "--path", "scripts/rope_ops.py"],
        ["log", "open", "polish topic hints", "--priority", "3"],
    ):
        result = run_ops(args, root, degraded)
        assert result.returncode == 0, result.stderr
    result = run_ops(["status"], root, degraded)
    assert result.returncode == 0, result.stderr
    result = run_ops(["jump"], root, degraded)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("# ROPE v1 | sess:")
    query = run_ops(["query", "degraded"], root, degraded)
    assert query.returncode == 0, query.stderr
    return (root / "ROPE.md").read_text(encoding="utf-8")


def assert_valid_rope(text: str) -> None:
    rope = RopeFile.parse(text)  # spec-conformant in both modes
    rope.validate()
    assert rope.jump_count == 1
    assert any("prove both modes" in g.text for g in rope.goals)
    assert "cwd" in rope.state


def test_installed_mode(tmp_path: Path) -> None:
    text = drive_workflow(tmp_path, degraded=False)
    assert_valid_rope(text)
    assert (tmp_path / ".jrope" / "turbovec.db").exists()


def test_degraded_mode(tmp_path: Path) -> None:
    text = drive_workflow(tmp_path, degraded=True)
    assert_valid_rope(text)
    assert not (tmp_path / ".jrope").exists()  # no TurboVec in degraded mode


def test_degraded_overflow_and_query(tmp_path: Path) -> None:
    run_ops(["init", "--budget", "120"], tmp_path, degraded=True)
    for i in range(40):
        result = run_ops(
            ["log", "decision", f"overflow decision {i} about the granite subsystem",
             "--reason", "pad", "--budget", "120"],
            tmp_path,
            degraded=True,
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / ".rope_overflow.md").exists()
    rope = RopeFile.parse((tmp_path / "ROPE.md").read_text(encoding="utf-8"))
    assert rope.keys, "demoted lines must leave K stubs"
    query = run_ops(["query", "granite subsystem"], tmp_path, degraded=True)
    assert query.returncode == 0
    assert query.stdout.startswith("RETRIEVED|")
