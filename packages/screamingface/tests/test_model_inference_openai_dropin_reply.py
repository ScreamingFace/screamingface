"""MI-42 to MI-44: the reply objects and the call keywords of OpenAI code (D23 to D25; C1.7).

FEATURE: SDK model inference, unit U10 (overview §5.6).
STORY: as a user of the OpenAI SDK, I append the reply message to my messages, I dump a reply
with model_dump(), I read an optional OpenAI attribute, and I keep my extra_headers. Each one
works after I change the client line.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from collections.abc import Iterator
from typing import Any

import httpx
import openai.resources.chat.completions
import pytest
from _chat_engine import answers, ok, recording_client, reply_body, sent_body, sse
from _chat_frames import TOOL_CALL, engine_stream, wire
from openai.types import CompletionUsage
from openai.types import chat as openai_chat
from openai.types.chat import (
    chat_completion,
    chat_completion_chunk,
    chat_completion_message_function_tool_call,
)

import screamingface as sf
from screamingface._inference.request import KNOWN_PARAMETERS, chat_messages, chat_tools
from screamingface.chat_completion import (
    ChatChoice,
    ChatChunkChoice,
    ChatCompletion,
    ChatCompletionChunk,
    ChatDelta,
    ChatDeltaToolCall,
    ChatFunctionCall,
    ChatMessage,
    ChatToolCall,
    ChatUsage,
)
from screamingface.inference import AsyncCompletions, Completions, RecipeCompletions
from screamingface.warnings import IgnoredParameterWarning

MODEL = "openrouter/a"
MESSAGES = [{"role": "user", "content": "What is the weather in Paris?"}]
TOOL = {"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}
TOOL_RESULT = {"role": "tool", "tool_call_id": "call_1", "content": "Sunny in Paris"}
TOOL_STREAM = wire(engine_stream({"role": "assistant"}, "tool_calls", tool_calls=(TOOL_CALL,)))
IGNORED: dict[str, Any] = {
    "extra_headers": {"X-Secret-Header": "s3cret-value"},
    "extra_query": {"secret": "s3cret-value"},
    "extra_body": {"provider": {"secret": "s3cret-value"}},
    "prediction": {"type": "content", "content": "x"},
    "web_search_options": {},
    "prompt_cache_key": "k",
    "prompt_cache_options": {},
    "prompt_cache_retention": "24h",
    "safety_identifier": "u",
    "verbosity": "low",
    "moderation": {},
}
# The OpenAI attributes that the Engine never sets (C1.7).
NONE_ATTRIBUTES: dict[type, tuple[str, ...]] = {
    ChatCompletion: ("system_fingerprint", "service_tier", "moderation"),
    ChatChoice: ("logprobs",),
    ChatMessage: ("function_call", "audio", "annotations"),
    ChatUsage: ("prompt_tokens_details", "completion_tokens_details"),
    ChatCompletionChunk: ("system_fingerprint", "service_tier", "moderation"),
    ChatChunkChoice: ("logprobs",),
    ChatDelta: ("function_call",),
}


def _tool_reply() -> ChatCompletion:
    with recording_client(answers(sse(TOOL_STREAM)), []) as client:
        # WHY no tools=: a call with tools is refused for now (C1.8); the mock Engine answers with
        # a tool call, so the reply types of a tool call stay covered.
        return client.chat.completions.create(model=MODEL, messages=MESSAGES)


def _chunks() -> list[ChatCompletionChunk]:
    with recording_client(answers(sse(TOOL_STREAM)), []) as client:
        return list(client.chat.completions.create(model=MODEL, messages=MESSAGES, stream=True))


def _objects() -> list[Any]:
    """One object of each reply type, from a real reply and a real stream."""

    reply = _tool_reply()
    chunks = _chunks()
    message = reply.choices[0].message
    assert message.tool_calls is not None
    tool_chunk = next(c for c in chunks if c.choices and c.choices[0].delta.tool_calls)
    delta = tool_chunk.choices[0].delta
    assert delta.tool_calls is not None
    assert reply.screamingface.final_step is not None
    return [
        reply,
        reply.choices[0],
        message,
        message.tool_calls[0],
        message.tool_calls[0].function,
        reply.usage,
        reply.screamingface,
        reply.screamingface.final_step,
        *chunks,
        tool_chunk.choices[0],
        delta,
        delta.tool_calls[0],
    ]


def _no_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _no_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_no_none(item) for item in value]
    return value


# MI-42: a reply message as an item of messages; iterables.


def test_the_reply_message_is_a_valid_item_of_messages() -> None:
    requests: list[httpx.Request] = []
    follow_up = {"role": "user", "content": "And in Lyon?"}
    with recording_client(answers(sse(reply_body("Sunny")), sse(reply_body())), requests) as client:
        first = client.chat.completions.create(model=MODEL, messages=MESSAGES)
        messages = [*MESSAGES, first.choices[0].message, follow_up]
        second = client.chat.completions.create(model=MODEL, messages=messages)

    assert second.text == "Hello"
    # INVARIANT (D23): the wire form of the OpenAI SDK for its own message object.
    assert sent_body(requests[1])["messages"] == [
        MESSAGES[0],
        {"role": "assistant", "content": "Sunny"},
        follow_up,
    ]
    assert messages[1] is first.choices[0].message


def test_a_reply_message_with_tool_calls_has_the_openai_wire_form() -> None:
    # WHY at the helper: a call with a tool turn is refused for now (C1.8, D27).
    message = _tool_reply().choices[0].message
    assert chat_messages(None, [*MESSAGES, message, TOOL_RESULT]) == [
        MESSAGES[0],
        {"role": "assistant", "content": None, "tool_calls": [TOOL_CALL]},
        TOOL_RESULT,
    ]


@pytest.mark.parametrize(
    ("message", "sent"),
    [
        (
            ChatMessage(role="assistant", content="Hello", tool_calls=None, refusal=None),
            {"role": "assistant", "content": "Hello"},
        ),
        (
            ChatMessage(role="assistant", content=None, tool_calls=None, refusal="No."),
            {"role": "assistant", "content": None, "refusal": "No."},
        ),
        (
            ChatMessage(role="assistant", content=None, tool_calls=(), refusal=None),
            {"role": "assistant", "content": None},
        ),
    ],
    ids=["text", "refusal", "empty-tool-calls"],
)
def test_a_reply_message_has_the_openai_wire_form(message: ChatMessage, sent: Any) -> None:
    assert chat_messages(None, [MESSAGES[0], message]) == [MESSAGES[0], sent]


def test_messages_and_tools_accept_each_iterable() -> None:
    def items(values: list[Any]) -> Iterator[Any]:
        yield from values

    assert chat_messages(None, items(MESSAGES)) == MESSAGES
    assert chat_messages(None, tuple(MESSAGES)) == MESSAGES
    assert chat_messages(None, dict.fromkeys(["a"], MESSAGES[0]).values()) == MESSAGES
    assert chat_tools(items([TOOL])) == [TOOL]
    assert chat_tools(items([])) is None
    with recording_client(ok, requests := []) as client:
        client.chat.completions.create(model=MODEL, messages=items(MESSAGES), tools=items([]))
    assert sent_body(requests[0])["messages"] == MESSAGES
    assert "tools" not in sent_body(requests[0])


@pytest.mark.parametrize(
    ("build", "error"),
    [
        (lambda: chat_messages(None, iter([])), ValueError),
        (lambda: chat_messages(None, MESSAGES[0]), TypeError),
        (lambda: chat_messages(None, b"hi"), TypeError),
        (lambda: chat_messages(None, 5), TypeError),
        (lambda: chat_messages(None, [object()]), TypeError),
        (lambda: chat_messages(None, [ChatMessage]), TypeError),
        (lambda: chat_tools(TOOL), TypeError),
        (lambda: chat_tools([_tool_reply().choices[0].message]), TypeError),
    ],
    ids=[
        "empty-iterator",
        "messages-mapping",
        "messages-bytes",
        "messages-int",
        "item-object",
        "item-class",
        "tools-mapping",
        "tools-message-item",
    ],
)
def test_messages_and_tools_argument_errors(build: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        build()


# MI-43: the OpenAI attributes with no value, and the dump methods.


def test_openai_attributes_that_the_engine_never_sets_are_none() -> None:
    by_type = {type(item): item for item in _objects()}
    for cls, names in NONE_ATTRIBUTES.items():
        for name in names:
            assert getattr(by_type[cls], name) is None, (cls.__name__, name)
            # C1.7: not a dataclass field, so the constructor and to_dict() do not change.
            assert name not in {field.name for field in dataclasses.fields(cls)}
            assert name not in by_type[cls].to_dict()
            with pytest.raises(AttributeError):
                setattr(by_type[cls], name, 1)
    assert all(not hasattr(item, "__dict__") for item in by_type.values())


@pytest.mark.parametrize(
    ("theirs", "ours"),
    [
        (openai_chat.ChatCompletion, ChatCompletion),
        (chat_completion.Choice, ChatChoice),
        (openai_chat.ChatCompletionMessage, ChatMessage),
        (openai_chat.ChatCompletionMessageFunctionToolCall, ChatToolCall),
        (CompletionUsage, ChatUsage),
        (openai_chat.ChatCompletionChunk, ChatCompletionChunk),
        (chat_completion_chunk.Choice, ChatChunkChoice),
        (chat_completion_chunk.ChoiceDelta, ChatDelta),
        (chat_completion_chunk.ChoiceDeltaToolCall, ChatDeltaToolCall),
        (chat_completion_chunk.ChoiceDeltaToolCallFunction, ChatFunctionCall),
        (chat_completion_message_function_tool_call.Function, ChatFunctionCall),
    ],
    ids=lambda value: value.__name__,
)
def test_each_field_of_an_openai_reply_object_is_an_attribute(theirs: Any, ours: type) -> None:
    """A tripwire: a later openai version that adds a field makes this test fail."""

    assert [name for name in theirs.model_fields if not hasattr(ours, name)] == []


def test_model_dump_is_the_dict_of_to_dict() -> None:
    for item in _objects():
        assert item.model_dump() == item.to_dict()
        assert item.model_dump() is not item.model_dump()
        assert item.model_dump(exclude_none=True) == _no_none(item.to_dict())
    message = _tool_reply().choices[0].message
    assert message.model_dump(exclude_none=True) == {"role": "assistant", "tool_calls": [TOOL_CALL]}


def test_model_dump_json_and_to_json_are_json_text_of_that_dict() -> None:
    for item in _objects():
        data = item.to_dict()
        assert item.model_dump_json() == json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        assert item.model_dump_json(indent=2) == json.dumps(data, indent=2, ensure_ascii=False)
        assert json.loads(item.model_dump_json(exclude_none=True)) == _no_none(data)
        assert item.to_json() == item.model_dump_json(indent=2)
        assert item.to_json(indent=None) == item.model_dump_json()


def test_the_json_text_keeps_text_that_is_not_ascii() -> None:
    with recording_client(answers(sse(reply_body("Olá, 世界"))), []) as client:
        reply = client.chat.completions.create("Hello", model=MODEL)
    assert "Olá, 世界" in reply.model_dump_json()
    assert "Olá, 世界" in reply.to_json()
    with pytest.raises(TypeError):
        reply.model_dump(unknown=True)  # type: ignore[call-arg]


# MI-44: the keywords of the OpenAI create.


@pytest.mark.parametrize(
    "create",
    [
        Completions.create,
        AsyncCompletions.create,
        RecipeCompletions.create,
        sf.chat.completions.create,
    ],
    ids=["client", "async-client", "recipe", "module"],
)
def test_each_parameter_of_the_openai_create_is_accepted(create: Any) -> None:
    """A tripwire: a later openai version that adds a parameter makes this test fail."""

    openai_create = openai.resources.chat.completions.Completions.create
    theirs = set(inspect.signature(openai_create).parameters)
    named = set(inspect.signature(create).parameters) | {"self", "model"}
    assert sorted(theirs - named - KNOWN_PARAMETERS) == []
    assert set(IGNORED) <= KNOWN_PARAMETERS
    assert named.isdisjoint(KNOWN_PARAMETERS)


def test_the_new_openai_keywords_warn_and_are_not_sent() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        client.chat.completions.create(model=MODEL, messages=MESSAGES)
        with pytest.warns(IgnoredParameterWarning) as record:
            client.chat.completions.create(model=MODEL, messages=MESSAGES, **IGNORED)
        with pytest.warns(IgnoredParameterWarning) as none_record:
            client.chat.completions.create("Hello", model=MODEL, functions=[], function_call="auto")

    assert sorted(str(item.message).split("'")[1] for item in record) == sorted(IGNORED)
    assert len(none_record) == 2
    # The advice of the sampling parameters does not apply to these names.
    assert all("sf.Model(" not in str(item.message) for item in [*record, *none_record])
    plain, extra = requests[0], requests[1]
    assert sent_body(extra) == sent_body(plain)
    assert extra.url == plain.url
    assert "x-secret-header" not in extra.headers
    assert "s3cret-value" not in extra.content.decode() + str(extra.url) + str(extra.headers)
