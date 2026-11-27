"""The text view and the native messages of the final step (tool-calls §3.4 and §3.5).

The text view is a candidate-input envelope, so each generated view is read back with the parser
that the Case reader uses. The generated cases come from _chat_conversations.py (plan decision D8).
"""

from __future__ import annotations

import copy
import json
from typing import Any

from _chat_conversations import (
    PNG,
    UNKNOWN_KEY,
    UNKNOWN_VALUE,
    cases,
    known_conversation,
    provider_state_conversation,
    without_unknown,
)

from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    parse_candidate_input,
)
from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_SCHEMA,
    CANDIDATE_INPUT_V2_SCHEMA,
)
from screamingface_engine.chat import wire
from screamingface_engine.chat.views import (
    CONVERSATION_MARKER,
    TOOLS_NOTE,
    native_messages,
    text_view,
)


def _request(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> wire.ChatCompletionRequest:
    """A request validated the way the route validates it."""

    body: dict[str, Any] = {"model": "m", "messages": messages}
    if tools is not None:
        body["tools"] = tools
    return wire.ChatCompletionRequest.model_validate(body)


def _rendered(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """The messages of the text view of a request."""

    req = _request(messages, tools)
    return json.loads(text_view(req.messages, req.tools))["messages"]


def _text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _report(index: int, body: dict[str, Any]) -> str:
    """The failure message of a generated case: its index and its input."""

    return f"case {index}: {json.dumps(body, ensure_ascii=False)}"


def _input_texts(body: dict[str, Any]) -> list[str]:
    """The non-empty text of every text part the client sent, in any message."""

    texts: list[str] = []
    for message in body["messages"]:
        content = message.get("content")
        if isinstance(content, list):
            texts.extend(
                part["text"] for part in content if part["type"] == "text" and part["text"]
            )
    return texts


def _output_text(content: Any) -> str:
    """The text of one output content: a string, or its text parts joined."""

    if isinstance(content, str):
        return content
    return "\n".join(part["text"] for part in content if part["type"] == "text")


def _part_list_is_valid(output: dict[str, Any]) -> bool:
    """A part list is a user message with a picture or file, and no empty text part."""

    parts = output["content"]
    return (
        output["role"] == "user"
        and any(part["type"] in ("image_url", "file") for part in parts)
        and all(part.get("text") != "" for part in parts)
    )


def test_text_view_is_valid_v1_or_v2_envelope_for_any_tool_history() -> None:
    """TC-5: every generated view is an envelope that the Case reader accepts."""

    for index, body in cases():
        req = wire.ChatCompletionRequest.model_validate(body)
        view = text_view(req.messages, req.tools)
        try:
            parsed = parse_candidate_input(view)
        except CandidateInputError as error:
            raise AssertionError(_report(index, body)) from error
        assert parsed, _report(index, body)
        envelope = json.loads(view)
        has_list = any(isinstance(message["content"], list) for message in envelope["messages"])
        expected = CANDIDATE_INPUT_V2_SCHEMA if has_list else CANDIDATE_INPUT_SCHEMA
        assert envelope["schema"] == expected, _report(index, body)


def test_text_view_is_deterministic() -> None:
    """TC-6: the same input gives the same bytes, from a copy of the body and on a second call."""

    for index, body in cases():
        req = wire.ChatCompletionRequest.model_validate(body)
        again = wire.ChatCompletionRequest.model_validate(copy.deepcopy(body))
        first = text_view(req.messages, req.tools).encode("utf-8")
        second = text_view(again.messages, again.tools).encode("utf-8")
        assert second == first, _report(index, body)
        assert text_view(req.messages, req.tools).encode("utf-8") == first, _report(index, body)


def test_text_view_joins_text_part_lists_and_drops_empty_parts() -> None:
    """TC-34: a part list keeps its picture or file, drops empty text, and loses no text."""

    for index, body in cases():
        req = wire.ChatCompletionRequest.model_validate(body)
        outputs = json.loads(text_view(req.messages, req.tools))["messages"]
        lists = [output for output in outputs if isinstance(output["content"], list)]
        assert all(_part_list_is_valid(output) for output in lists), _report(index, body)
        output_texts = [_output_text(output["content"]) for output in outputs]
        for text in _input_texts(body):
            assert any(text in output_text for output_text in output_texts), _report(index, body)


def _view_bytes(body: dict[str, Any]) -> bytes:
    req = wire.ChatCompletionRequest.model_validate(body)
    return text_view(req.messages, req.tools).encode("utf-8")


def test_text_view_ignores_unknown_keys() -> None:
    """Rules 0 to 6: an unknown key never reaches the view, so its bytes do not change."""

    messages, tools = provider_state_conversation()
    plain_messages, plain_tools = known_conversation()
    with_keys = _view_bytes({"model": "m", "messages": messages, "tools": tools})
    assert with_keys == _view_bytes(
        {"model": "m", "messages": plain_messages, "tools": plain_tools}
    )

    carried = 0
    for index, body in cases():
        carried += UNKNOWN_KEY in json.dumps(body)
        view = _view_bytes(body)
        assert UNKNOWN_VALUE.encode() not in view, _report(index, body)
        assert view == _view_bytes(without_unknown(body)), _report(index, body)
    assert carried


def test_text_view_part_list_examples() -> None:
    """TC-34: the three examples of the rule."""

    joined = _rendered(
        [{"role": "user", "content": [_text_part("a"), _text_part(""), _text_part("b")]}]
    )
    assert joined == [{"role": "user", "content": "a\nb"}]

    empty = _rendered([{"role": "system", "content": [_text_part("")]}])
    assert empty == [{"role": "system", "content": ""}]

    pictured = _rendered(
        [
            {
                "role": "user",
                "content": [
                    _text_part(""),
                    {"type": "image_url", "image_url": {"url": PNG}},
                    _text_part("q"),
                ],
            }
        ]
    )
    assert pictured == [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": PNG}}, _text_part("q")],
        }
    ]


def test_text_view_without_tool_history_equals_plain_envelope() -> None:
    """TC-7: with no tool history and no tools, the view is the plain envelope."""

    req = _request(
        [
            {"role": "system", "content": "S"},
            {"role": "developer", "content": "D"},
            {"role": "user", "content": "U ü"},
            {"role": "assistant", "content": "A"},
        ]
    )
    expected = json.dumps(
        {
            "schema": CANDIDATE_INPUT_SCHEMA,
            "messages": [
                {"role": "system", "content": "S"},
                {"role": "developer", "content": "D"},
                {"role": "user", "content": "U ü"},
                {"role": "assistant", "content": "A"},
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert text_view(req.messages, req.tools) == expected

    parts = [_text_part("Q"), {"type": "image_url", "image_url": {"url": PNG, "detail": "low"}}]
    pictured = json.loads(_view_of([{"role": "user", "content": parts}]))
    assert pictured == {
        "schema": CANDIDATE_INPUT_V2_SCHEMA,
        "messages": [{"role": "user", "content": parts}],
    }


def _view_of(messages: list[dict[str, Any]]) -> str:
    req = _request(messages)
    return text_view(req.messages, req.tools)


def test_text_view_renders_tool_calls_and_results_as_lines() -> None:
    """Rules 2 and 3: a tool call is a line of its assistant message, tool results join."""

    rendered = _rendered(
        [
            {
                "role": "assistant",
                "content": "Let me look.",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "read", "arguments": '{"p":"a"}'},
                    },
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {"name": "list", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "A"},
            {"role": "tool", "tool_call_id": "c2", "content": [_text_part("B")]},
            {"role": "user", "content": "next"},
        ]
    )
    assert rendered == [
        {
            "role": "assistant",
            "content": (
                'Let me look.\n[tool_call id=c1 name=read] {"p":"a"}\n'
                "[tool_call id=c2 name=list] {}"
            ),
        },
        {"role": "user", "content": "[tool_result id=c1] A\n[tool_result id=c2] B"},
        {"role": "user", "content": "next"},
    ]


def test_text_view_lists_tools_in_a_first_system_message() -> None:
    """Rule 4: the tools follow a first system message; no tools means no note."""

    tools = [
        {
            "type": "function",
            "function": {"name": "read", "description": "Read.", "parameters": {"type": "object"}},
        }
    ]
    rendered = _rendered([{"role": "system", "content": "S"}], tools)
    assert rendered[0] == {
        "role": "system",
        "content": TOOLS_NOTE
        + "\n"
        + '{"description":"Read.","name":"read","parameters":{"type":"object"}}',
    }
    assert rendered[1] == {"role": "system", "content": "S"}

    assert _rendered([{"role": "system", "content": "S"}], []) == [
        {"role": "system", "content": "S"}
    ]


def test_native_messages_keep_client_messages_unchanged_between_intent_and_context() -> None:
    """TC-8: the instruction, then the client messages as sent, then the context with a marker."""

    raw = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "Q"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "R"},
    ]
    req = _request(raw)
    input_text = text_view(req.messages, req.tools)
    context = json.dumps({"input": input_text, "outputs": {"member_1": "draft"}})

    result = native_messages(
        req.messages, instruction="Synthesize.", context=context, input_text=input_text
    )

    assert result[0] == {"role": "system", "content": "Synthesize."}
    assert result[1:-1] == raw
    assert result[-1] == {
        "role": "user",
        "content": json.dumps({"input": CONVERSATION_MARKER, "outputs": {"member_1": "draft"}}),
    }


def test_native_messages_keep_unknown_keys() -> None:
    """Tool-calls §3.5: the final step gets the client messages with no change, unknown keys too."""

    messages, tools = provider_state_conversation()
    req = _request(messages, tools)

    result = native_messages(req.messages, instruction="I", context=None, input_text="IN")

    assert result == [{"role": "system", "content": "I"}, *messages]


def test_native_messages_add_no_system_or_context_message_when_empty() -> None:
    """TC-8: an empty instruction, an empty context or a context equal to the input adds nothing."""

    req = _request([{"role": "user", "content": "Q"}])
    only_client = [{"role": "user", "content": "Q"}]

    assert (
        native_messages(req.messages, instruction="", context=None, input_text="IN") == only_client
    )
    assert native_messages(req.messages, instruction="", context="", input_text="IN") == only_client
    assert (
        native_messages(req.messages, instruction="", context="IN", input_text="IN") == only_client
    )

    draft = native_messages(req.messages, instruction="", context="plain draft", input_text="IN")
    assert draft == [*only_client, {"role": "user", "content": "plain draft"}]
