"""Model adapters: scripted reader behavior, live adapter retrieval loop."""

from __future__ import annotations

import sys

from ropebench.models import OpenAICompatModel, ScriptedModel

CONTEXT = """cwd:/srv/app
the amber anchor pipeline is pinned to build argon-4412 until further notice
decided to adopt basalt-queue for the flange layer because of latency constraints
K3|svc/keel.py/mod/the dusky keel pipeline is|tv-abc123
routine change 4: linted the shell scripts across the module"""


def test_scripted_finds_fact_line() -> None:
    answer = ScriptedModel().answer(
        CONTEXT, "What build is the amber anchor pipeline pinned to?"
    )
    assert "argon-4412" in answer.text
    assert not answer.used_retrieval


def test_scripted_finds_decision_line() -> None:
    answer = ScriptedModel().answer(CONTEXT, "What did we adopt for the flange layer?")
    assert "basalt-queue" in answer.text


def test_scripted_prefers_latest_mention_on_ties() -> None:
    context = (
        "new goal (pending): ship the keel migration\n"
        "goal status update: ship the keel migration is now done"
    )
    question = "What is the status of the goal to ship the keel migration?"
    answer = ScriptedModel().answer(context, question)
    assert "done" in answer.text


def test_scripted_never_answers_with_a_stub_and_uses_retrieval() -> None:
    calls: list[str] = []

    def retrieve(query: str) -> str:
        calls.append(query)
        return (
            "RETRIEVED|tv-abc123|the dusky keel pipeline is pinned to "
            "build flint-9001 until further notice"
        )

    answer = ScriptedModel().answer(
        CONTEXT, "What build is the dusky keel pipeline pinned to?", retrieve
    )
    assert "flint-9001" in answer.text
    assert answer.used_retrieval and calls
    assert not answer.text.startswith("K3|")


def test_scripted_admits_ignorance() -> None:
    answer = ScriptedModel().answer(CONTEXT, "What color is the moon lobster?")
    assert answer.text == "no recollection of that detail"


def test_live_adapter_plain_answer() -> None:
    model = OpenAICompatModel(
        base_url="http://x/v1", model="m",
        chat_fn=lambda messages: "the pipeline is pinned to argon-4412",
    )
    answer = model.answer(CONTEXT, "What build is the pipeline pinned to?")
    assert "argon-4412" in answer.text
    assert not answer.used_retrieval


def test_live_adapter_retrieval_loop() -> None:
    replies = iter(["RETRIEVE: dusky keel pinned build", "it is pinned to flint-9001"])
    seen_messages: list[list[dict[str, str]]] = []

    def chat_fn(messages: list[dict[str, str]]) -> str:
        seen_messages.append(list(messages))
        return next(replies)

    model = OpenAICompatModel(base_url="http://x/v1", model="m", chat_fn=chat_fn)
    answer = model.answer(
        CONTEXT,
        "What build is the dusky keel pipeline pinned to?",
        retrieve=lambda q: "RETRIEVED|tv-abc123|pinned to build flint-9001",
    )
    assert "flint-9001" in answer.text
    assert answer.used_retrieval
    assert answer.extra_tokens > 0
    # Second round carries the retrieval result back to the model.
    assert "RETRIEVAL RESULT" in seen_messages[1][-1]["content"]


def test_live_adapter_bounded_retrieval_rounds() -> None:
    model = OpenAICompatModel(
        base_url="http://x/v1", model="m",
        chat_fn=lambda messages: "RETRIEVE: forever",
        max_retrieval_rounds=2,
    )
    answer = model.answer(CONTEXT, "q?", retrieve=lambda q: "RETRIEVED|k|nothing")
    assert answer.text.startswith("RETRIEVE:")  # gave up after the cap


FAKE_CMD = [
    sys.executable, "-c",
    "import sys; d = sys.stdin.read(); "
    "print('RETRIEVE: pinned build' if 'RETRIEVAL RESULT' not in d "
    "else 'it is pinned to flint-9001')",
]


def test_command_model_plain_and_retrieval_loop() -> None:
    from ropebench.models import CommandModel

    model = CommandModel(argv=FAKE_CMD)
    answer = model.answer(
        CONTEXT,
        "What build is the dusky keel pipeline pinned to?",
        retrieve=lambda q: "RETRIEVED|tv-abc|pinned to build flint-9001",
    )
    assert "flint-9001" in answer.text
    assert answer.used_retrieval


def test_command_model_failure_scores_as_miss() -> None:
    from ropebench.models import CommandModel

    model = CommandModel(argv=[sys.executable, "-c", "import sys; sys.exit(3)"])
    answer = model.answer(CONTEXT, "anything?")
    assert answer.text == ""
