"""MI-6, MI-16, MI-17, MI-18, MI-19, MI-23 and MI-29 through ModelInference with a sync client
(contracts C1.2, C2.1)."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
from _chat_engine import (
    CHAT_PATH,
    answers,
    catalogue_engine,
    envelope,
    fake_time,
    ok,
    recording_client,
    reply_body,
    sent_body,
    sse,
    trace_id_of,
)
from _chat_frames import TOOL_CALL, TRACE_ID, engine_stream, info, wire

import screamingface as sf
from screamingface import _default_client
from screamingface._evaluation.candidate import compile_candidate
from screamingface.chat_completion import (
    ChatCompletion,
    ChatFunctionCall,
    ChatToolCall,
    ChatUsage,
)
from screamingface.client import Client
from screamingface.errors import ExecutionError, PlanningError
from screamingface.inference import ModelInference
from screamingface.recipe import Recipe
from screamingface.warnings import IgnoredParameterWarning


def test_one_prompt_sends_one_streamed_request_and_gives_a_reply() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        reply = ModelInference(sf.Model("openrouter/a"), client=client).chat.complete("Hello")

    [request] = requests
    assert request.url.path == CHAT_PATH
    assert sent_body(request) == {
        "model": compile_candidate(sf.Model("openrouter/a")).url4,
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    assert request.headers["accept"] == "text/event-stream"
    assert request.headers["content-type"].startswith("application/json")
    assert "traceparent" in request.headers
    assert "cache-control" not in request.headers
    assert isinstance(reply, ChatCompletion)
    assert reply.text == reply.choices[0].message.content == "Hello"
    assert reply.usage == ChatUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5)
    assert reply.cost_usd == Decimal("0.0012")
    assert reply.trace_id == TRACE_ID


def test_a_model_id_is_sent_unchanged() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        ModelInference("openrouter/a", client=client).chat.complete("Hello")

    assert sent_body(requests[0])["model"] == "openrouter/a"


def test_use_cache_false_sends_no_store() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        ModelInference("openrouter/a", client=client).chat.complete("Hello", use_cache=False)

    assert requests[0].headers["cache-control"] == "no-store"


def test_each_call_has_a_new_traceparent() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        llm = ModelInference("openrouter/a", client=client)
        llm.chat.complete("one")
        llm.chat.complete("two")

    assert len(requests) == 2
    assert trace_id_of(requests[0]) != trace_id_of(requests[1])


def test_messages_and_tools_are_sent_unchanged() -> None:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "Be short."},
        {"role": "user", "content": [{"type": "text", "text": "Hi"}]},
    ]
    tools: list[dict[str, Any]] = [
        {"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}
    ]
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        ModelInference("openrouter/a", client=client).chat.complete(messages=messages, tools=tools)

    body = sent_body(requests[0])
    assert body["messages"] == messages
    assert body["tools"] == tools


def test_complete_does_not_send_empty_tools() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        ModelInference("openrouter/a", client=client).chat.complete("Hello", tools=[])

    assert "tools" not in sent_body(requests[0])


def test_tool_calls_are_on_the_reply() -> None:
    handler = answers(
        sse(wire(engine_stream({"role": "assistant"}, "tool_calls", tool_calls=(TOOL_CALL,))))
    )
    with recording_client(handler, []) as client:
        reply = ModelInference("openrouter/a", client=client).chat.complete("Hello")

    assert reply.text is None
    assert reply.choices[0].finish_reason == "tool_calls"
    assert reply.tool_calls == (
        ChatToolCall(
            id="call_1",
            type="function",
            function=ChatFunctionCall(name="get_weather", arguments='{"city":"Paris"}'),
        ),
    )


@pytest.mark.parametrize(
    ("payload", "status", "text", "refusal"),
    [
        pytest.param(
            engine_stream(
                {"role": "assistant", "content": ""},
                "stop",
                screamingface=info(status="abstained", abstain_reason="budget_refused"),
            ),
            "abstained",
            "",
            None,
            id="abstained",
        ),
        pytest.param(
            engine_stream(
                {"role": "assistant", "content": None, "refusal": "no"},
                "content_filter",
                screamingface=info(status="refused", final_step=None),
            ),
            "refused",
            None,
            "no",
            id="refused",
        ),
    ],
)
def test_abstained_and_refused_are_replies(
    payload: list[dict[str, Any]], status: str, text: str | None, refusal: str | None
) -> None:
    with recording_client(answers(sse(wire(payload))), []) as client:
        reply = ModelInference("openrouter/a", client=client).chat.complete("Hello")

    assert reply.screamingface.status == status
    assert reply.text == text
    assert reply.choices[0].message.refusal == refusal


def test_complete_warns_for_known_parameters_and_does_not_send_them() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        llm = ModelInference("openrouter/a", client=client)
        with pytest.warns(IgnoredParameterWarning) as record:
            llm.chat.complete("Hello", temperature=0.2, max_tokens=50)

    assert len(record) == 2
    # WHY __file__: the warning names the line of the caller, which is this file.
    assert record[0].filename == __file__
    assert set(sent_body(requests[0])) == {"model", "messages", "stream", "stream_options"}


def test_refused_and_unknown_parameters_send_nothing() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        llm = ModelInference("openrouter/a", client=client)
        with pytest.raises(PlanningError) as refused:
            llm.chat.complete("Hello", n=2)
        assert refused.value.code == "unsupported_parameter"
        with pytest.raises(TypeError):
            llm.chat.complete("Hello", tool=[{}])

    assert requests == []


ARGUMENT_ERRORS: list[tuple[Callable[[ModelInference[Client]], object], type[Exception]]] = [
    (lambda llm: llm.chat.complete(), TypeError),
    (lambda llm: llm.chat.complete("hi", messages=[{"role": "user", "content": "x"}]), TypeError),
    (lambda llm: llm.chat.complete(messages=[]), ValueError),
    (lambda llm: llm.chat.complete("hi", timeout=0), ValueError),
    (lambda llm: llm.chat.complete("hi", max_retries=-1), ValueError),
    (lambda llm: llm.chat.complete("hi", stream=cast(Any, "yes")), TypeError),
]


@pytest.mark.parametrize(("call", "error"), ARGUMENT_ERRORS)
def test_argument_errors_send_no_request(
    call: Callable[[ModelInference[Client]], object], error: type[Exception]
) -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        llm = ModelInference("openrouter/a", client=client)
        with pytest.raises(error):
            call(llm)

    assert requests == []


def test_constructor_argument_errors() -> None:
    with pytest.raises(TypeError):
        ModelInference(cast(Any, 5))
    with pytest.raises(ValueError):
        ModelInference("  ")
    with pytest.raises(TypeError):
        ModelInference("openrouter/a", client=cast(Any, object()))


def test_engine_errors_reach_the_caller() -> None:
    requests: list[httpx.Request] = []
    handler = answers(
        envelope(429, "overloaded", headers={"x-should-retry": "true", "Retry-After": "3"})
    )
    with recording_client(handler, requests) as client:
        with pytest.raises(ExecutionError) as raised:
            ModelInference("openrouter/a", client=client).chat.complete("Hello")

    assert raised.value.permanent is False
    assert raised.value.details == {"retry_after": 3}
    assert raised.value.trace_id == trace_id_of(requests[0])


def test_max_retries_and_timeout_reach_the_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    handler = answers(
        envelope(429, "overloaded", headers={"x-should-retry": "true", "Retry-After": "1"}),
        sse(reply_body()),
    )
    with recording_client(handler, requests) as client:
        reply = ModelInference("openrouter/a", client=client).chat.complete(
            "Hello", max_retries=1, timeout=50.0
        )

    assert reply.text == "Hello"
    assert len(requests) == 2
    assert fake.sleeps == [1.0]
    assert requests[0].extensions["timeout"]["read"] == 50.0


def test_default_client_is_taken_at_each_call(monkeypatch: pytest.MonkeyPatch) -> None:
    first_requests: list[httpx.Request] = []
    second_requests: list[httpx.Request] = []
    first = recording_client(ok, first_requests)
    second = recording_client(ok, second_requests)
    monkeypatch.setattr(_default_client, "_client", first)
    llm = ModelInference("openrouter/a")
    try:
        llm.chat.complete("one")
        # WHY sf.close(): it closes the first client and forgets it, as the next call needs.
        sf.close()
        monkeypatch.setattr(_default_client, "_client", second)
        llm.chat.complete("two")
    finally:
        second.close()

    assert len(first_requests) == 1
    assert len(second_requests) == 1


@pytest.mark.parametrize(
    "model",
    ["openrouter/a", sf.Fanout(["prov/a", "prov/b"]) >> sf.Vote()],
)
def test_closed_client_raises_before_a_request(model: Recipe | str) -> None:
    requests: list[httpx.Request] = []
    client = recording_client(catalogue_engine, requests)
    client.close()

    with pytest.raises(RuntimeError, match="Client is closed"):
        ModelInference(model, client=client).chat.complete("Hello")

    assert requests == []
