"""Review round 2 follow-up: the ignored names are read before the main parse (CC-S35), and
READ_PARAMETERS is the field set of the wire model (RR-S12)."""

from __future__ import annotations

import json

import pytest

from screamingface_engine.chat.wire import ChatCompletionRequest
from screamingface_engine.rest import chat_body
from screamingface_engine.rest.chat_errors import ChatError
from screamingface_engine.rest.chat_ignored import READ_PARAMETERS, ignored_parameters


def test_ignored_names_are_read_before_the_main_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    real = chat_body.ignored_parameters

    def spy_ignored(raw: bytes) -> tuple[str, ...]:
        order.append("ignored")
        return real(raw)

    class _SpyModel:
        @staticmethod
        def model_validate_json(raw: bytes) -> ChatCompletionRequest:
            order.append("validate")
            return ChatCompletionRequest.model_validate_json(raw)

    monkeypatch.setattr(chat_body, "ignored_parameters", spy_ignored)
    monkeypatch.setattr(chat_body, "ChatCompletionRequest", _SpyModel)
    raw = json.dumps(
        {"model": "m", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2}
    ).encode()

    body = chat_body._checked(raw)

    assert order == ["ignored", "validate"]
    assert body.ignored_parameters == ("temperature",)


def test_ignored_names_of_a_body_that_is_not_json_are_empty() -> None:
    assert ignored_parameters(b"{not json") == ()
    assert ignored_parameters(b"[1, 2]") == ()
    assert ignored_parameters(b"") == ()


def test_a_body_that_is_not_json_still_gets_invalid_request() -> None:
    with pytest.raises(ChatError) as info:
        chat_body._checked(b"{not json")

    assert info.value.status == 400
    assert info.value.code == "invalid_request"


def test_read_parameters_is_the_field_set_of_the_wire_model() -> None:
    assert READ_PARAMETERS == frozenset(ChatCompletionRequest.model_fields)
    assert all(field.alias is None for field in ChatCompletionRequest.model_fields.values())
    assert READ_PARAMETERS == frozenset(
        {
            "model",
            "messages",
            "tools",
            "functions",
            "stream",
            "stream_options",
            "n",
            "logprobs",
            "modalities",
            "audio",
        }
    )
