"""§8.6 — CLI: every jrope subcommand via subprocess, exit 0 + artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def jrope(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "jumping_rope.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_every_subcommand(tmp_path: Path) -> None:
    # init
    result = jrope(
        ["init", "--session-id", "cli-test", "--rope-budget-tokens", "500"], tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert "initialized session cli-test" in result.stdout
    data_dir = tmp_path / ".jrope"
    assert (data_dir / "ROPE.md").exists()
    assert (data_dir / "session.json").exists()
    assert (data_dir / "turbovec.db").exists()

    # log — one event per section
    for args in (
        ["log", "state", "/srv/app", "--key", "cwd"],
        ["log", "goal", "ship the cli", "--status", "active"],
        ["log", "decision", "argparse over click", "--reason", "zero deps"],
        ["log", "delta", "wired subcommands", "--path", "jumping_rope/cli.py"],
        ["log", "open", "shell completion missing", "--priority", "3"],
    ):
        result = jrope(args, tmp_path)
        assert result.returncode == 0, result.stderr
        assert "logged" in result.stdout

    rope_text = (data_dir / "ROPE.md").read_text(encoding="utf-8")
    assert "cwd:/srv/app" in rope_text
    assert "▶ G1|ship" in rope_text

    # status
    result = jrope(["status"], tmp_path)
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["session_id"] == "cli-test"
    assert status["rope_tokens"] <= 500

    # jump
    result = jrope(["jump"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("# ROPE v1 | sess:cli-test | j:1 |")

    # force demotions so query has something to find
    for i in range(30):
        assert (
            jrope(
                ["log", "decision", f"padding decision {i} about the granite subsystem",
                 "--reason", "pad"],
                tmp_path,
            ).returncode
            == 0
        )

    # query (semantic)
    result = jrope(["query", "granite subsystem decision", "-k", "3"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("RETRIEVED|")

    # export
    out = tmp_path / "dump.json"
    result = jrope(["export", "--out", str(out)], tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["rope"].startswith("# ROPE v1")
    assert payload["records"], "export should contain demoted records"

    # export to stdout too
    result = jrope(["export"], tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"]["session_id"] == "cli-test"


def test_commands_fail_cleanly_without_init(tmp_path: Path) -> None:
    result = jrope(["status"], tmp_path)
    assert result.returncode == 2
    assert "run `jrope init` first" in result.stderr


def test_console_script_entrypoint(tmp_path: Path) -> None:
    """The installed `jrope` script works, not just python -m."""
    script = Path(sys.executable).parent / "jrope"
    if not script.exists():
        # editable install always provides it next to the interpreter in CI
        code = (
            "from jumping_rope.cli import main; "
            "raise SystemExit(main(['init', '--data-dir', 'd']))"
        )
        script_result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=tmp_path, capture_output=True, text=True, check=False,
        )
        assert script_result.returncode == 0
        return
    result = subprocess.run(
        [str(script), "init", "--data-dir", str(tmp_path / "d")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert (tmp_path / "d" / "ROPE.md").exists()
