"""§8.8 — Proxy adapter e2e with TestClient against a stub upstream."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from jumping_rope import JumpConfig
from jumping_rope.tokens import count_tokens

_PROXY_PATH = (
    Path(__file__).resolve().parent.parent / "adapters" / "openrouter" / "proxy.py"
)


def load_proxy_module() -> Any:
    spec = importlib.util.spec_from_file_location("jrope_proxy", _PROXY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["jrope_proxy"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def stub(tmp_path: Path) -> tuple[TestClient, list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append(payload)
        return httpx.Response(
            200,
            json={
                "id": f"stub-{len(captured)}",
                "choices": [
                    {"message": {"role": "assistant", "content": f"stub reply {len(captured)}"}}
                ],
            },
        )

    module = load_proxy_module()
    app = module.create_app(
        upstream_url="http://stub-upstream/v1",
        upstream_key="test-key",
        data_dir=tmp_path / "proxy-data",
        config=JumpConfig(jump_every_n_turns=4, jump_threshold_tokens=50_000),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return TestClient(app), captured


def test_ten_requests_jump_cadence_and_payload(
    stub: tuple[TestClient, list[dict[str, Any]]],
) -> None:
    client, captured = stub
    history: list[dict[str, Any]] = []
    jumped_flags: list[str] = []
    for i in range(10):
        history.append(
            {
                "role": "user",
                "content": f"request {i}: "
                + "verbose exposition about the data pipeline and its backfill. " * 100,
            }
        )
        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": history},
            headers={"X-JRope-Session": "proxy-sess"},
        )
        assert response.status_code == 200
        assert response.headers["X-JRope-Session"] == "proxy-sess"
        jumped_flags.append(response.headers["X-JRope-Jumped"])
        history.append(
            {
                "role": "assistant",
                "content": response.json()["choices"][0]["message"]["content"],
            }
        )

    # every-4-turns cadence over 10 requests → jumps at request 4 and 8.
    assert jumped_flags == ["0", "0", "0", "1", "0", "0", "0", "1", "0", "0"]

    jump_payloads = [
        c
        for c in captured
        if len(c["messages"]) == 2 and c["messages"][0]["role"] == "system"
    ]
    assert len(jump_payloads) == 2
    ratios: list[float] = []
    for payload, idx in zip(jump_payloads, (3, 7), strict=True):
        assert payload["messages"][0]["content"].startswith("# ROPE v1")
        assert payload["messages"][1]["role"] == "user"
        # Naive payload for this request: the full history the client sent.
        naive = sum(count_tokens(str(m["content"])) for m in history[: 2 * idx + 1])
        outbound = sum(count_tokens(str(m["content"])) for m in payload["messages"])
        ratios.append(outbound / naive)
        print(f"\n[proxy] naive={naive} outbound={outbound} ratio={outbound / naive:.1%}")
    assert ratios[-1] < 0.20, f"final-jump outbound is {ratios[-1]:.1%} of naive"


def test_header_based_session_routing(
    stub: tuple[TestClient, list[dict[str, Any]]],
) -> None:
    client, _captured = stub
    body = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    r_a = client.post("/v1/chat/completions", json=body, headers={"X-JRope-Session": "a"})
    r_b = client.post("/v1/chat/completions", json=body, headers={"X-JRope-Session": "b"})
    assert r_a.headers["X-JRope-Session"] == "a"
    assert r_b.headers["X-JRope-Session"] == "b"
    # No header → deterministic hash of first user message.
    r_c = client.post("/v1/chat/completions", json=body)
    r_d = client.post("/v1/chat/completions", json=body)
    assert r_c.headers["X-JRope-Session"] == r_d.headers["X-JRope-Session"]
    assert len(r_c.headers["X-JRope-Session"]) == 16


def test_upstream_auth_header_forwarded(tmp_path: Path) -> None:
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization"))
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        )

    module = load_proxy_module()
    app = module.create_app(
        upstream_url="http://stub/v1",
        upstream_key="sk-secret",
        data_dir=tmp_path / "d",
        config=JumpConfig(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = TestClient(app)
    client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "x"}]},
    )
    assert seen_auth == ["Bearer sk-secret"]
    assert client.get("/health").json()["status"] == "ok"
