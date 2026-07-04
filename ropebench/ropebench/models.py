"""Model adapters.

ScriptedModel is a deterministic literal reader — the CI-mode responder. It
measures *information availability*: whether a regime's context (plus its
retrieval tool) makes the answer findable at all. Live mode swaps in a real
model over any OpenAI-compatible endpoint and measures *information use*.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from jumping_rope.tokens import count_tokens

from .regimes import RetrieveFn

_SUFFIXES = ("ing", "ed", "es", "ly", "s")
_STOPWORDS = {
    "the", "and", "not", "for", "with", "into", "only", "after", "every",
    "what", "which", "did", "does", "goal", "status", "now", "until",
    "further", "notice", "because",
}
_STUB_LINE = re.compile(r"^K\d+\|")  # rope KEYS stubs are pointers, not answers


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> set[str]:
    return {
        _stem(w)
        for w in re.split(r"[^0-9a-z-]+", text.casefold())
        if len(w) >= 3 and w not in _STOPWORDS and _stem(w) not in _STOPWORDS
    }


@dataclass
class ModelAnswer:
    text: str
    extra_tokens: int = 0  # tokens spent beyond the base context (retrieval etc.)
    used_retrieval: bool = False


class Model(Protocol):
    """Anything that can answer a probe given a context and optional tool."""

    def answer(
        self, context: str, question: str, retrieve: RetrieveFn | None = None
    ) -> ModelAnswer: ...


class ScriptedModel:
    """Literal-minded reader: best-overlap line (≥2 shared content words),
    with one retrieval fallback if the regime offers a tool."""

    name = "scripted"

    def _best_line(self, text: str, qtok: set[str]) -> tuple[str, int, bool]:
        """(best line, overlap, stub_matched). Later lines win ties — a
        literal reader trusts the most recent mention. KEYS stubs are never
        answers; a matching stub signals that retrieval is warranted."""
        best, best_n, stub_matched = "", 0, False
        for line in text.splitlines():
            if line.startswith(("## ", "# ")):
                continue
            n = len(_tokens(line) & qtok)
            if _STUB_LINE.match(line):
                if n >= 1:
                    stub_matched = True
                continue
            if n >= best_n and n > 0:
                best_n, best = n, line
        return best, best_n, stub_matched

    def answer(
        self, context: str, question: str, retrieve: RetrieveFn | None = None
    ) -> ModelAnswer:
        qtok = _tokens(question)
        line, overlap, stub_matched = self._best_line(context, qtok)
        # Confident direct answer needs near-full question overlap — a
        # partial match (e.g. another pipeline's line sharing generic words)
        # is a look-alike, not an answer.
        required = max(2, len(qtok) - 1)
        if overlap >= required:
            return ModelAnswer(text=line)
        if retrieve is not None:
            retrieved = retrieve(question)
            r_line, r_overlap, _ = self._best_line(retrieved, qtok)
            if r_overlap >= 2 and r_overlap > overlap:
                return ModelAnswer(
                    text=r_line,
                    extra_tokens=count_tokens(retrieved),
                    used_retrieval=True,
                )
        if overlap >= 2:  # weak direct answer beats silence
            return ModelAnswer(text=line)
        return ModelAnswer(text="no recollection of that detail")


SYSTEM_PROMPT = (
    "You are an agent resuming work after a context clear. The CONTEXT block "
    "below is everything you have; do not invent details that are not in it. "
    "Answer the question in one short sentence quoting the exact value or "
    "line. If the context lacks the detail and retrieval is available, reply "
    "with exactly `RETRIEVE: <search query>` and nothing else."
)

ChatFn = Callable[[list[dict[str, str]]], str]


class CommandModel:
    """Live-mode adapter that shells out to a CLI model (e.g. `claude -p
    --model haiku`). The prompt goes to stdin, the reply is stdout. The
    RETRIEVE: protocol works via re-invocation with the retrieval result
    appended. A failed or timed-out invocation scores as a miss instead of
    crashing the sweep."""

    name = "command"

    def __init__(
        self,
        argv: list[str],
        max_retrieval_rounds: int = 2,
        timeout_s: int = 120,
    ) -> None:
        self.argv = argv
        self.max_retrieval_rounds = max_retrieval_rounds
        self.timeout_s = timeout_s

    def _chat(self, prompt: str) -> str:
        try:
            proc = subprocess.run(
                self.argv, input=prompt, capture_output=True, text=True,
                timeout=self.timeout_s, check=False,
            )
        except subprocess.TimeoutExpired:
            return ""
        return proc.stdout.strip()

    def answer(
        self, context: str, question: str, retrieve: RetrieveFn | None = None
    ) -> ModelAnswer:
        retrieval_note = (
            "" if retrieve is None else "\n(retrieval available via RETRIEVE:)"
        )
        prompt = (
            f"{SYSTEM_PROMPT}\n\nCONTEXT:\n{context}\n\n"
            f"QUESTION: {question}{retrieval_note}"
        )
        extra = 0
        used_retrieval = False
        for _ in range(self.max_retrieval_rounds + 1):
            reply = self._chat(prompt)
            match = re.match(r"^RETRIEVE:\s*(.+)$", reply, re.IGNORECASE)
            if match is None or retrieve is None:
                return ModelAnswer(
                    text=reply, extra_tokens=extra, used_retrieval=used_retrieval
                )
            retrieved = retrieve(match.group(1).strip())
            used_retrieval = True
            extra += count_tokens(retrieved)
            prompt = (
                f"{prompt}\n\nRETRIEVAL RESULT:\n{retrieved}\n\n"
                f"QUESTION: {question}"
            )
        return ModelAnswer(text=reply, extra_tokens=extra, used_retrieval=used_retrieval)


class OpenAICompatModel:
    """Live-mode adapter for any /v1/chat/completions upstream.

    ``chat_fn`` is injectable for tests; the default posts with urllib.
    """

    name = "live"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        chat_fn: ChatFn | None = None,
        max_retrieval_rounds: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.chat_fn = chat_fn or self._http_chat
        self.max_retrieval_rounds = max_retrieval_rounds

    def _http_chat(self, messages: list[dict[str, str]]) -> str:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(
                {"model": self.model, "messages": messages, "temperature": 0}
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload["choices"][0]["message"]["content"])

    def answer(
        self, context: str, question: str, retrieve: RetrieveFn | None = None
    ) -> ModelAnswer:
        retrieval_note = (
            "" if retrieve is None else "\n(retrieval available via RETRIEVE:)"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}{retrieval_note}",
            },
        ]
        extra = 0
        used_retrieval = False
        for _ in range(self.max_retrieval_rounds + 1):
            reply = self.chat_fn(messages).strip()
            match = re.match(r"^RETRIEVE:\s*(.+)$", reply, re.IGNORECASE)
            if match is None or retrieve is None:
                return ModelAnswer(
                    text=reply, extra_tokens=extra, used_retrieval=used_retrieval
                )
            retrieved = retrieve(match.group(1).strip())
            used_retrieval = True
            extra += count_tokens(retrieved)
            messages.append({"role": "assistant", "content": reply})
            messages.append(
                {
                    "role": "user",
                    "content": f"RETRIEVAL RESULT:\n{retrieved}\n\nQUESTION: {question}",
                }
            )
        return ModelAnswer(text=reply, extra_tokens=extra, used_retrieval=used_retrieval)
