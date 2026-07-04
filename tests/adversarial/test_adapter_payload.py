"""A13 — adapter payload attack: the LAST user message is itself ~8K tokens.

The jump must still fire, the outbound payload must carry the rope PLUS the
full untruncated last message, the rope-portion cap applies to the rope only,
and the naive-baseline comparison must not false-pass just because the giant
message inflated the baseline.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from jumping_rope import JumpConfig
from jumping_rope.tokens import count_tokens

_ADAPTERS = Path(__file__).resolve().parent.parent.parent / "adapters"

GIANT = ("the migration ledger must reconcile shard boundaries before cutover. " * 800)
GIANT_TOKENS = count_tokens(GIANT)


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_a13_pipe_giant_last_message(tmp_path: Path) -> None:
    assert GIANT_TOKENS >= 8_000, f"payload only {GIANT_TOKENS} tokens"
    module = _load("jumping_rope_pipe_a13", _ADAPTERS / "openwebui" / "jumping_rope_pipe.py")
    pipe = module.Pipe()
    pipe.valves.MODE = "bound"
    pipe.valves.DATA_DIR = str(tmp_path / "pipe")
    pipe.valves.JUMP_EVERY_N_TURNS = 3
    pipe.valves.JUMP_THRESHOLD_TOKENS = 50_000
    captured: list[dict[str, Any]] = []
    pipe.upstream_fn = lambda payload: (
        captured.append(payload),
        {"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
    )[1]

    history: list[dict[str, Any]] = []
    for i in range(2):
        history.append({"role": "user", "content": f"small turn {i} about the ledger"})
        pipe.pipe({"messages": list(history), "metadata": {"chat_id": "a13"}})
        history.append({"role": "assistant", "content": "ok"})
    history.append({"role": "user", "content": GIANT})  # turn 3 → jump fires
    response = pipe.pipe({"messages": list(history), "metadata": {"chat_id": "a13"}})

    assert response["jumping_rope"]["jumped"] is True
    outbound = captured[-1]["messages"]
    assert [m["role"] for m in outbound] == ["system", "user"]
    # The giant user message rides along COMPLETE — never truncated.
    assert outbound[1]["content"] == GIANT
    # The A3 cap applies to the rope portion only.
    rope_tokens = count_tokens(outbound[0]["content"])
    assert rope_tokens <= 2_000, f"rope portion is {rope_tokens} tokens"
    assert outbound[0]["content"].startswith("# ROPE v1")
    # No false-pass via baseline inflation: when one message dominates the
    # history, an outbound/naive ratio is meaningless (outbound = rope +
    # giant can even exceed naive by the rope's fixed overhead). The honest
    # check is the rope portion in isolation: bounded, and small relative
    # to the message it escorts.
    naive = sum(count_tokens(str(m["content"])) for m in history)
    outbound_total = sum(count_tokens(str(m["content"])) for m in outbound)
    assert outbound_total - GIANT_TOKENS == rope_tokens  # rope + giant, nothing else
    assert rope_tokens < GIANT_TOKENS * 0.05, "rope overhead should be marginal"
    print(f"\n[a13-pipe] giant={GIANT_TOKENS} rope={rope_tokens} "
          f"naive={naive} outbound={outbound_total}")


def test_a13_proxy_giant_last_message(tmp_path: Path) -> None:
    module = _load("jrope_proxy_a13", _ADAPTERS / "openrouter" / "proxy.py")
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        )

    app = module.create_app(
        upstream_url="http://stub/v1",
        data_dir=tmp_path / "proxy",
        config=JumpConfig(jump_every_n_turns=3, jump_threshold_tokens=50_000),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = TestClient(app)
    history: list[dict[str, Any]] = []
    for i in range(2):
        history.append({"role": "user", "content": f"small turn {i} about the ledger"})
        client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": history},
            headers={"X-JRope-Session": "a13"},
        )
        history.append({"role": "assistant", "content": "ok"})
    history.append({"role": "user", "content": GIANT})
    response = client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": history},
        headers={"X-JRope-Session": "a13"},
    )

    assert response.headers["X-JRope-Jumped"] == "1"
    outbound = captured[-1]["messages"]
    assert [m["role"] for m in outbound] == ["system", "user"]
    assert outbound[1]["content"] == GIANT  # untruncated
    rope_tokens = count_tokens(outbound[0]["content"])
    assert rope_tokens <= 2_000
    print(f"\n[a13-proxy] giant={GIANT_TOKENS} rope={rope_tokens}")
