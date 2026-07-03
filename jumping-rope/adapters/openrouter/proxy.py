"""Jumping Rope middleware proxy: OpenAI-compatible /v1/chat/completions.

Sits between any client and any OpenAI-compatible upstream (OpenRouter,
LiteLLM, Ollama) and transparently maintains a rope per session. When the
naive history breaches the jump thresholds, the forwarded history is replaced
by ``[system: rope] + [last user message]``.

Configuration (environment):
    JROPE_UPSTREAM_URL   upstream base URL, e.g. https://openrouter.ai/api/v1
    JROPE_UPSTREAM_KEY   bearer token for the upstream (optional)
    JROPE_DATA_DIR       rope/TurboVec storage dir (default ./jrope-proxy-data)
    JROPE_BUDGET_TOKENS / JROPE_THRESHOLD_TOKENS / JROPE_EVERY_N_TURNS
    JROPE_PROFILE        notation profile (default symbolic-en)

Session routing: header ``X-JRope-Session`` if present, else a hash of the
first user message.

Run:
    uvicorn adapters.openrouter.proxy:app --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.handoff import apply_jump_policy, apply_streaming_policy, record_turn

SESSION_HEADER = "X-JRope-Session"


def _config_from_env() -> JumpConfig:
    return JumpConfig(
        rope_budget_tokens=int(os.environ.get("JROPE_BUDGET_TOKENS", "2000")),
        jump_threshold_tokens=int(os.environ.get("JROPE_THRESHOLD_TOKENS", "12000")),
        jump_every_n_turns=int(os.environ.get("JROPE_EVERY_N_TURNS", "8")),
        notation_profile=os.environ.get("JROPE_PROFILE", "symbolic-en"),
    )


def create_app(
    upstream_url: str | None = None,
    upstream_key: str | None = None,
    data_dir: str | Path | None = None,
    config: JumpConfig | None = None,
    client: httpx.AsyncClient | None = None,
    mode: str | None = None,
) -> FastAPI:
    app = FastAPI(title="Jumping Rope Proxy", version="1.0.0")
    app.state.upstream_url = (
        upstream_url
        or os.environ.get("JROPE_UPSTREAM_URL", "http://localhost:11434/v1")
    ).rstrip("/")
    app.state.upstream_key = (
        upstream_key if upstream_key is not None else os.environ.get("JROPE_UPSTREAM_KEY", "")
    )
    app.state.data_dir = Path(
        data_dir or os.environ.get("JROPE_DATA_DIR", "./jrope-proxy-data")
    )
    app.state.config = config or _config_from_env()
    # Mode resolution: explicit param > env > derived from an explicit
    # config > default unbound. A caller who hands us a bounded config
    # gets bound behavior without also having to say so.
    if mode is not None:
        app.state.mode = mode
    elif "JROPE_MODE" in os.environ:
        app.state.mode = os.environ["JROPE_MODE"]
    elif config is not None:
        app.state.mode = config.mode
    else:
        app.state.mode = "unbound"
    if app.state.mode == "unbound" and config is None:
        app.state.config = JumpConfig.unbound(
            notation_profile=app.state.config.notation_profile
        )
    app.state.client = client or httpx.AsyncClient(timeout=120.0)
    app.state.sessions = {}

    def _session_for(request: Request, messages: list[dict[str, Any]]) -> JumpingRopeSession:
        sid = request.headers.get(SESSION_HEADER)
        if not sid:
            first_user = next(
                (str(m.get("content", "")) for m in messages if m.get("role") == "user"),
                "default",
            )
            sid = hashlib.sha256(first_user.encode("utf-8")).hexdigest()[:16]
        sessions: dict[str, JumpingRopeSession] = app.state.sessions
        if sid not in sessions:
            sessions[sid] = JumpingRopeSession(
                app.state.data_dir / sid, session_id=sid, config=app.state.config
            )
        return sessions[sid]

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "upstream": app.state.upstream_url}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> JSONResponse:
        body = await request.json()
        messages: list[dict[str, Any]] = list(body.get("messages", []))
        session = _session_for(request, messages)

        if app.state.mode == "unbound":
            outbound, jumped = apply_streaming_policy(session, messages)
        else:
            record_turn(session, messages)
            outbound, jumped = apply_jump_policy(session, messages)
        payload = {**body, "messages": outbound}

        headers = {"Content-Type": "application/json"}
        if app.state.upstream_key:
            headers["Authorization"] = f"Bearer {app.state.upstream_key}"
        upstream_response = await app.state.client.post(
            f"{app.state.upstream_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        data = upstream_response.json()

        try:
            reply = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            reply = ""
        if isinstance(reply, str) and reply.strip():
            head = " ".join(reply.split()[:8])
            session.archive(topic=f"assistant: {head}", content=reply)

        return JSONResponse(
            content=data,
            status_code=upstream_response.status_code,
            headers={
                SESSION_HEADER: session.meta.session_id,
                "X-JRope-Jumped": "1" if jumped else "0",
                "X-JRope-Outbound-Messages": str(len(outbound)),
            },
        )

    return app


app = create_app()
