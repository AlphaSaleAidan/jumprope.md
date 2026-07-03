"""§8.7 — Open WebUI pipe adapter against a fake upstream."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from jumping_rope.tokens import count_tokens

_PIPE_PATH = (
    Path(__file__).resolve().parent.parent / "adapters" / "openwebui" / "jumping_rope_pipe.py"
)


def load_pipe_module() -> Any:
    spec = importlib.util.spec_from_file_location("jumping_rope_pipe", _PIPE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["jumping_rope_pipe"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def pipe(tmp_path: Path) -> Any:
    module = load_pipe_module()
    p = module.Pipe()
    p.valves.DATA_DIR = str(tmp_path / "pipe-data")
    p.valves.JUMP_EVERY_N_TURNS = 5
    p.valves.JUMP_THRESHOLD_TOKENS = 50_000
    p.valves.ROPE_BUDGET_TOKENS = 2_000
    return p


def test_twelve_turns_exact_jump_count_and_payload_shape(pipe: Any) -> None:
    captured: list[dict[str, Any]] = []

    def fake_upstream(payload: dict[str, Any]) -> dict[str, Any]:
        captured.append(payload)
        return {
            "choices": [
                {"message": {"role": "assistant", "content": f"assistant reply {len(captured)}"}}
            ]
        }

    pipe.upstream_fn = fake_upstream

    history: list[dict[str, Any]] = []
    naive_tokens_at_jump: list[int] = []
    outbound_tokens_at_jump: list[int] = []
    for i in range(12):
        history.append(
            {
                "role": "user",
                "content": (
                    f"turn {i}: "
                    + "long user message about the ongoing migration of the "
                    "billing subsystem, repeated context and boilerplate details. "
                    * 40
                ),
            }
        )
        body = {"messages": list(history), "metadata": {"chat_id": "convo-1"}}
        response = pipe.pipe(body)
        assert response["choices"][0]["message"]["content"]
        if response["jumping_rope"]["jumped"]:
            naive = sum(count_tokens(str(m["content"])) for m in history)
            outbound = sum(
                count_tokens(str(m["content"])) for m in captured[-1]["messages"]
            )
            naive_tokens_at_jump.append(naive)
            outbound_tokens_at_jump.append(outbound)
        history.append(
            {"role": "assistant", "content": response["choices"][0]["message"]["content"]}
        )

    # Exactly the expected number of jumps: every 5th turn → turns 5 and 10.
    jump_payloads = [
        c
        for c in captured
        if len(c["messages"]) == 2
        and c["messages"][0]["role"] == "system"
        and c["messages"][0]["content"].startswith("# ROPE v1")
    ]
    assert len(jump_payloads) == 2

    # Post-jump outbound = system-rope + last user message ONLY.
    for payload in jump_payloads:
        assert [m["role"] for m in payload["messages"]] == ["system", "user"]
        assert payload["messages"][1]["content"].startswith("turn")

    # Outbound payload under 20% of the naive full-history payload once the
    # history is long (the final jump). Earlier jumps are printed for context —
    # the rope has a fixed floor (legend + anchors), so the ratio falls as the
    # naive history grows.
    for naive, outbound in zip(
        naive_tokens_at_jump, outbound_tokens_at_jump, strict=True
    ):
        print(f"\n[pipe] naive={naive} outbound={outbound} ratio={outbound / naive:.1%}")
    final_ratio = outbound_tokens_at_jump[-1] / naive_tokens_at_jump[-1]
    assert final_ratio < 0.20, f"final-jump outbound is {final_ratio:.1%} of naive"


def test_conversation_id_fallback_hash(pipe: Any) -> None:
    pipe.upstream_fn = lambda payload: {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}]
    }
    body = {"messages": [{"role": "user", "content": "hello there"}]}
    response = pipe.pipe(body)
    sid = response["jumping_rope"]["session_id"]
    assert len(sid) == 16  # sha-256 prefix of the first user message
    # Same first message → same session.
    response2 = pipe.pipe(body)
    assert response2["jumping_rope"]["session_id"] == sid


def test_passthrough_params_forwarded(pipe: Any) -> None:
    seen: list[dict[str, Any]] = []
    pipe.upstream_fn = lambda payload: (
        seen.append(payload),
        {"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
    )[1]
    pipe.pipe(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.2,
            "max_tokens": 64,
            "metadata": {"chat_id": "c9"},
        }
    )
    assert seen[0]["temperature"] == 0.2
    assert seen[0]["max_tokens"] == 64
    assert seen[0]["stream"] is False
