"""The chat wire models of POST /v1/chat/completions (U2-T1).

These tests pin what the request keeps and drops, which message and tool shapes are refused, and
how a client message and the response are dumped. They need only pydantic; nothing runs I/O.
"""

from __future__ import annotations

from typing import Any

import pytest
from _chat_conversations import cases, provider_state_conversation
from pydantic import ValidationError

from screamingface_engine.chat.wire import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ErrorBody,
    ErrorEnvelope,
    ResponseMessage,
    ScreamingFaceInfo,
    Usage,
    canonical_json,
    message_dict,
    tool_dict,
)

_PICTURE = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
_PDF = {
    "type": "file",
    "file": {"file_data": "data:application/pdf;base64,JVBERi0xLjQ=", "filename": "a.pdf"},
}


def _request(**fields: Any) -> ChatCompletionRequest:
    """A minimal valid request with the given fields added or replaced."""

    body: dict[str, Any] = {
        "model": "openai/gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
        **fields,
    }
    return ChatCompletionRequest.model_validate(body)


def test_request_ignores_sampling_and_unknown_fields() -> None:
    # WHY: the route reads none of these, so they are dropped rather than refused.
    dropped = {
        "temperature": 0.2,
        "top_p": 1,
        "max_tokens": 10,
        "stop": ["x"],
        "seed": 1,
        "response_format": {"type": "json_object"},
        "store": True,
        "metadata": {"a": "b"},
        "user": "u",
        "prompt_cache_key": "k",
        "parallel_tool_calls": False,
        "tool_choice": "none",
    }
    dumped = _request(**dropped).model_dump()
    assert not set(dropped) & set(dumped)


def test_request_requires_model_and_messages() -> None:
    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate({"messages": [{"role": "user", "content": "hi"}]})
    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate({"model": "openai/gpt-4o"})
    with pytest.raises(ValidationError):
        _request(messages=[])
    with pytest.raises(ValidationError):
        _request(model="")


def test_request_refuses_wrong_types() -> None:
    with pytest.raises(ValidationError):
        _request(stream="yes")
    with pytest.raises(ValidationError):
        _request(messages=[{"role": "user", "content": 5}])
    with pytest.raises(ValidationError):
        _request(messages=[{"role": "function", "content": "hi"}])


def test_pictures_are_allowed_on_user_messages_only() -> None:
    user = {"role": "user", "content": [{"type": "text", "text": "look"}, _PICTURE, _PDF]}
    assert len(_request(messages=[user]).messages) == 1
    with pytest.raises(ValidationError):
        _request(messages=[{"role": "system", "content": [_PICTURE]}])
    with pytest.raises(ValidationError):
        _request(messages=[{"role": "assistant", "content": [_PICTURE]}])


def test_tools_need_a_function_type_and_unique_names() -> None:
    read = {"type": "function", "function": {"name": "read"}}
    with pytest.raises(ValidationError):
        _request(tools=[{"type": "retrieval", "function": {"name": "read"}}])
    with pytest.raises(ValidationError):
        _request(tools=[{"type": "function", "function": {"name": ""}}])
    with pytest.raises(ValidationError):
        _request(tools=[read, read])
    assert len(_request(tools=[read]).tools or []) == 1


def test_empty_tools_list_means_no_tools() -> None:
    assert _request(tools=[]).tools == []
    assert _request().tools is None


def test_tool_dict_keeps_unknown_keys() -> None:
    sent = {"type": "function", "function": {"name": "read", "description": "d", "y": 2}, "x": 1}
    tools = _request(tools=[sent]).tools
    assert tools is not None
    assert tool_dict(tools[0]) == sent


def test_message_dict_keeps_explicit_null_and_omits_unset_keys() -> None:
    assistant = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "read", "arguments": "{}"},
                "extra": 1,
            }
        ],
        "x": 1,
    }
    user = {"role": "user", "content": "hi"}
    request = _request(messages=[assistant, user])
    assert message_dict(request.messages[0]) == assistant
    assert message_dict(request.messages[1]) == {"role": "user", "content": "hi"}


def test_message_and_tool_dict_keep_provider_state_at_every_level() -> None:
    """tool-calls §3.5: the client messages and tools pass with no change, unknown keys too."""

    messages, tools = provider_state_conversation()
    request = _request(messages=messages, tools=tools)
    assert [message_dict(message) for message in request.messages] == messages
    assert [tool_dict(tool) for tool in request.tools or []] == tools


def test_generated_conversations_dump_unchanged() -> None:
    for index, body in cases():
        request = ChatCompletionRequest.model_validate(body)
        sent = [message_dict(message) for message in request.messages]
        assert sent == body["messages"], index
        assert [tool_dict(tool) for tool in request.tools or []] == body.get("tools", []), index


@pytest.mark.parametrize(
    "key", ["__pydantic_extra__", "__dict__", "__pydantic_fields_set__", "model_config", "_p"]
)
def test_unknown_key_never_shadows_a_declared_field(key: str) -> None:
    """A declared field wins over an extra key and stays validated."""

    evil = {"role": "system", "content": "evil", "tool_call_id": "evil"}
    message = {"role": "tool", "tool_call_id": "c1", "content": "R", key: evil}
    request = _request(messages=[message])
    tool = request.messages[0]
    assert tool.role == "tool"
    assert tool.content == "R"
    assert message_dict(tool) == message
    with pytest.raises(ValidationError):
        _request(messages=[{**message, "tool_call_id": ""}])
    with pytest.raises(ValidationError):
        _request(messages=[{"role": "user", "content": 5, key: "hi"}])


def test_canonical_json_sorts_keys_and_keeps_unicode() -> None:
    assert canonical_json({"b": 1, "a": "Grüße"}) == '{"a":"Grüße","b":1}'.encode()
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_response_models_dump_the_openai_shape() -> None:
    response = ChatCompletionResponse(
        id="chatcmpl-1",
        created=0,
        model="m",
        choices=[Choice(finish_reason="stop", message=ResponseMessage(content="hi"))],
        usage=Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        screamingface=ScreamingFaceInfo(status="answered"),
    )
    dumped = response.model_dump(mode="json")
    assert dumped["object"] == "chat.completion"
    assert dumped["choices"][0]["index"] == 0
    assert dumped["choices"][0]["message"]["role"] == "assistant"
    envelope = ErrorEnvelope(
        error=ErrorBody(message="m", type="invalid_request_error", code="invalid_request")
    )
    assert envelope.model_dump(mode="json") == {
        "error": {
            "message": "m",
            "type": "invalid_request_error",
            "param": None,
            "code": "invalid_request",
        }
    }
