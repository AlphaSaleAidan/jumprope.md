"""Jumping Rope pipe function for Open WebUI.

Paste this file as a Pipe Function in Open WebUI (Workspace → Functions), or
mount it in a pipelines container. It intercepts every chat turn, maintains a
per-conversation rope + TurboVec store under ``DATA_DIR``, and when the live
context breaches the configured thresholds it performs the jump: the outgoing
history sent upstream is replaced by ``[system: rope] + [last user message]``.

Requires ``pip install jumping-rope`` in the Open WebUI environment. The
upstream must speak the OpenAI ``/v1/chat/completions`` protocol (OpenRouter,
LiteLLM, Ollama, vLLM, ...).

title: Jumping Rope
author: jumping-rope
version: 1.0.0
license: MIT
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.handoff import apply_jump_policy, apply_streaming_policy, record_turn


class Pipe:
    class Valves(BaseModel):
        UPSTREAM_URL: str = Field(
            default="http://localhost:11434/v1",
            description="OpenAI-compatible upstream base URL (OpenRouter, Ollama, ...)",
        )
        UPSTREAM_KEY: str = Field(default="", description="Bearer token for the upstream")
        MODEL_ID: str = Field(
            default="deepseek/deepseek-chat", description="Model id sent upstream"
        )
        MODE: str = Field(
            default="unbound",
            description="'unbound': rope grows freely, transcript evicted "
            "continuously once captured. 'bound': hard rope budget, "
            "episodic jumps.",
        )
        JUMP_THRESHOLD_TOKENS: int = Field(
            default=12_000, description="Jump when naive history exceeds this"
        )
        JUMP_EVERY_N_TURNS: int = Field(
            default=8, description="Jump at least every N turns"
        )
        ROPE_BUDGET_TOKENS: int = Field(
            default=2_000, description="Hard token budget for the rope file"
        )
        NOTATION_PROFILE: str = Field(
            default="symbolic-en", description="symbolic-en or cjk-dense"
        )
        DATA_DIR: str = Field(
            default="./jrope-data", description="Where ropes and TurboVec DBs live"
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        # Test seam: replace with any callable(payload) -> response dict.
        self.upstream_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None
        self._sessions: dict[str, JumpingRopeSession] = {}

    # -- session plumbing ---------------------------------------------------

    def _conversation_id(self, body: dict[str, Any]) -> str:
        meta = body.get("metadata") or {}
        chat_id = meta.get("chat_id") or body.get("chat_id")
        if chat_id:
            return str(chat_id)
        for message in body.get("messages", []):
            if message.get("role") == "user":
                content = str(message.get("content", ""))
                return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        return "default"

    def _session(self, convo_id: str) -> JumpingRopeSession:
        if convo_id not in self._sessions:
            budget = 0 if self.valves.MODE == "unbound" else self.valves.ROPE_BUDGET_TOKENS
            config = JumpConfig(
                rope_budget_tokens=budget,
                jump_threshold_tokens=self.valves.JUMP_THRESHOLD_TOKENS,
                jump_every_n_turns=self.valves.JUMP_EVERY_N_TURNS,
                notation_profile=self.valves.NOTATION_PROFILE,
            )
            self._sessions[convo_id] = JumpingRopeSession(
                Path(self.valves.DATA_DIR) / convo_id,
                session_id=convo_id,
                config=config,
            )
        return self._sessions[convo_id]

    # -- upstream -----------------------------------------------------------

    def _call_upstream(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.upstream_fn is not None:
            return self.upstream_fn(payload)
        url = self.valves.UPSTREAM_URL.rstrip("/") + "/chat/completions"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **(
                    {"Authorization": f"Bearer {self.valves.UPSTREAM_KEY}"}
                    if self.valves.UPSTREAM_KEY
                    else {}
                ),
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return dict(json.loads(response.read().decode("utf-8")))

    # -- the pipe -----------------------------------------------------------

    def pipe(self, body: dict[str, Any]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = list(body.get("messages", []))
        session = self._session(self._conversation_id(body))

        if self.valves.MODE == "unbound":
            outbound, jumped = apply_streaming_policy(session, messages)
        else:
            record_turn(session, messages)
            outbound, jumped = apply_jump_policy(session, messages)

        payload: dict[str, Any] = {
            "model": self.valves.MODEL_ID,
            "messages": outbound,
            "stream": False,
        }
        for passthrough in ("temperature", "max_tokens", "top_p"):
            if passthrough in body:
                payload[passthrough] = body[passthrough]

        response = self._call_upstream(payload)

        # Archive the assistant reply full-fidelity (tier 2).
        try:
            reply = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            reply = ""
        if isinstance(reply, str) and reply.strip():
            head = " ".join(reply.split()[:8])
            session.archive(topic=f"assistant: {head}", content=reply)

        response.setdefault("jumping_rope", {})
        response["jumping_rope"] = {
            "jumped": jumped,
            "session_id": session.meta.session_id,
            "outbound_messages": len(outbound),
        }
        return response
