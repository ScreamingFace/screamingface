"""MI-47 to MI-50: tool calls are turned off for now (overview §5.7, D26 to D28; contracts C1.8).

FEATURE: SDK model inference, unit U11. Owner decision of 2026-11-24: a call that declares or
uses a tool gets a clear error, from the SDK before a request and from the Engine for each other
client. The check is fixed; no setting turns it off.
STORY: as a developer, I pass tools= to a chat call and I get one clear error that tells me that
tool calls are not available yet, before a request and before a cost.
"""

from __future__ import annotations

import warnings
from typing import Any

import httpx
import pytest
from _chat_engine import (
    answers,
    envelope,
    model,
    ok,
    recording_client,
    reply_body,
    sent_body,
    sse,
)
from _chat_frames import TOOL_CALL, engine_stream, wire
from _chat_stream import async_recording_client

import screamingface as sf
from screamingface import _default_client
from screamingface.chat_completion import ChatMessage
from screamingface.errors import PlanningError
from screamingface.warnings import IgnoredParameterWarning

MODEL = "openrouter/a"
USER = {"role": "user", "content": "What is the weather in Paris?"}
TOOL = {"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}
ASSISTANT = {"role": "assistant", "content": None, "tool_calls": [TOOL_CALL]}
RESULT = {"role": "tool", "tool_call_id": "call_1", "content": "Sunny in Paris"}
CODE = "tools_not_available"


def _refused(call: Any, param: str) -> PlanningError:
    """Run the call; it must raise the tool error for `param` and give no warning."""

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(PlanningError) as raised:
            call()
    error = raised.value
    assert error.code == CODE
    assert error.permanent is True
    assert error.details == {"param": param}
    assert "Tool calls are not available yet" in str(error)
    # C1.2: a call that raises gives no warning.
    assert [item for item in caught if item.category is IgnoredParameterWarning] == []
    return error


def test_declared_tools_are_refused_before_a_request() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        error = _refused(
            lambda: client.chat.completions.create(
                model=MODEL, messages=[USER], tools=[TOOL], temperature=0.2
            ),
            "tools",
        )
        _refused(
            lambda: client.chat.completions.create("Hi", model=MODEL, tools=(TOOL,), stream=True),
            "tools",
        )

    assert "'tools'" in str(error)
    assert requests == []


@pytest.mark.parametrize(
    ("messages", "param"),
    [
        ([USER, ASSISTANT, RESULT], "messages[1].tool_calls"),
        ([USER, RESULT], "messages[1]"),
        ([USER, {"role": "assistant", "content": "x"}, USER, RESULT], "messages[3]"),
    ],
    ids=["assistant-tool-calls", "tool-message", "tool-message-later"],
)
def test_a_tool_turn_in_the_conversation_is_refused(messages: list[Any], param: str) -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        error = _refused(
            lambda: client.chat.completions.create(model=MODEL, messages=messages), param
        )

    assert param in str(error)
    assert requests == []


def test_a_reply_message_with_tool_calls_is_refused_as_a_messages_item() -> None:
    # The Engine does not give such a reply now. An object from another source is refused too.
    message = ChatMessage(role="assistant", content=None, tool_calls=(), refusal=None)
    requests: list[httpx.Request] = []
    tool_stream = wire(engine_stream({"role": "assistant"}, "tool_calls", tool_calls=(TOOL_CALL,)))
    handler = answers(sse(tool_stream), sse(reply_body()))
    with recording_client(handler, requests) as client:
        reply = client.chat.completions.create(model=MODEL, messages=[USER])
        with_calls = reply.choices[0].message
        assert with_calls.tool_calls is not None
        _refused(
            lambda: client.chat.completions.create(model=MODEL, messages=[USER, with_calls]),
            "messages[1].tool_calls",
        )
        # A message with an empty tool_calls value has no tool call.
        client.chat.completions.create(model=MODEL, messages=[USER, message, USER])

    assert len(requests) == 2
    assert "tool_calls" not in sent_body(requests[1])["messages"][1]


def test_each_surface_has_the_same_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        monkeypatch.setattr(_default_client, "default_client", lambda: client)
        _refused(lambda: sf.chat.completions.create("Hi", model=MODEL, tools=[TOOL]), "tools")
        _refused(lambda: model().chat.completions.create("Hi", tools=[TOOL]), "tools")
        _refused(lambda: model().chat.completions.create(messages=[USER, RESULT]), "messages[1]")

    assert requests == []


def test_an_argument_error_of_the_tool_refusal_makes_no_default_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made: list[int] = []
    monkeypatch.setattr(_default_client, "default_client", lambda: made.append(1))
    _refused(lambda: sf.chat.completions.create("Hi", model=MODEL, tools=[TOOL]), "tools")
    assert made == []


@pytest.mark.asyncio
async def test_the_async_call_itself_raises_the_refusal() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(ok, requests) as client:
        # C1.2: an argument error comes from the call, before a coroutine exists.
        _refused(lambda: client.chat.completions.create("Hi", model=MODEL, tools=[TOOL]), "tools")
        _refused(
            lambda: client.chat.completions.create(model=MODEL, messages=[USER, RESULT]),
            "messages[1]",
        )

    assert requests == []


def test_no_tools_is_not_tool_use() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        client.chat.completions.create("Hi", model=MODEL, tools=[])
        client.chat.completions.create("Hi", model=MODEL, tools=None)
        client.chat.completions.create("Hi", model=MODEL, tools=iter(()))
        client.chat.completions.create(
            model=MODEL, messages=[USER, {"role": "assistant", "content": "x", "tool_calls": None}]
        )

    assert len(requests) == 4
    assert all("tools" not in sent_body(request) for request in requests)


def test_the_old_functions_keyword_is_refused_and_the_choice_keywords_only_warn() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        error = _refused(
            lambda: client.chat.completions.create(
                "Hi", model=MODEL, functions=[{"name": "get_weather"}], function_call="auto"
            ),
            "functions",
        )
        assert "'functions'" in str(error)
        assert requests == []
        # tool_choice and function_call choose a tool; with no declared tool they do nothing.
        with pytest.warns(IgnoredParameterWarning) as record:
            client.chat.completions.create(
                "Hi", model=MODEL, tool_choice="auto", function_call="none", functions=[]
            )

    assert sorted(str(item.message).split("'")[1] for item in record) == [
        "function_call",
        "functions",
        "tool_choice",
    ]
    assert len(requests) == 1
    assert set(sent_body(requests[0])) & {"tool_choice", "function_call", "functions"} == set()


def test_the_engine_refusal_has_the_same_code() -> None:
    # An Engine with the check answers HTTP 400 before a run (the Engine test TC-23). A caller of
    # the SDK sees it only if the SDK check and the Engine check differ.
    refusal = envelope(
        400,
        CODE,
        message="tool calls are not available yet; remove the tools and the tool messages",
        param="tools",
    )
    requests: list[httpx.Request] = []
    with recording_client(answers(refusal), requests) as client:
        with pytest.raises(PlanningError) as raised:
            client.chat.completions.create("Hi", model=MODEL)

    assert raised.value.code == CODE
    assert raised.value.permanent is True
    assert "tool calls are not available yet" in str(raised.value)
    assert len(requests) == 1


def test_a_tool_call_in_a_reply_is_still_read() -> None:
    # INVARIANT (D28): the tool code stays. A reply with a tool call is read as before.
    tool_stream = wire(engine_stream({"role": "assistant"}, "tool_calls", tool_calls=(TOOL_CALL,)))
    with recording_client(answers(sse(tool_stream)), []) as client:
        reply = client.chat.completions.create("Hi", model=MODEL)

    assert reply.choices[0].finish_reason == "tool_calls"
    assert reply.tool_calls is not None
    assert reply.tool_calls[0].function.name == "get_weather"
