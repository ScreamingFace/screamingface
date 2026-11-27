"""The chat endpoint is documented under its own tag and names the OpenAI error envelope.

FEATURE (OME chat endpoint, Q9): `POST /v1/chat/completions` speaks the OpenAI `{"error": ...}`
envelope, not RFC 9457. The served `/openapi.json` must say so where a consumer reads the tag
it calls, and the API description must name the chat endpoint as the other exception.

WHY these assertions: the chat path is an OpenAI-compatible surface, so an SDK user reads the
Chat tag and the API description first. They must state the envelope and the mount split.
"""

from __future__ import annotations

from typing import Any

from screamingface_engine.app import create_app


def _schema() -> dict[str, Any]:
    return create_app().openapi()


def test_the_chat_path_is_documented_under_the_chat_tag() -> None:
    """The route declares no body parameter, so its request body is documented via openapi_extra."""
    op = _schema()["paths"]["/v1/chat/completions"]["post"]

    assert op["tags"] == ["Chat"]
    assert "requestBody" in op
    assert set(op["responses"]) >= {
        "200",
        "400",
        "401",
        "404",
        "413",
        "415",
        "429",
        "502",
        "503",
        "504",
    }


def test_the_chat_tag_states_the_openai_error_envelope() -> None:
    """A consumer reads the Chat tag, so it must name the OpenAI envelope and the exceptions."""
    tag = next(t for t in _schema()["tags"] if t["name"] == "Chat")
    description = tag["description"]

    assert "OpenAI" in description
    assert '{"error"' in description
    assert "RFC 9457" in description
    assert "mount" in description.casefold()


def test_the_api_description_names_the_chat_exception() -> None:
    """The one document every API consumer fetches names the chat path as the OpenAI dialect."""
    description = _schema()["info"]["description"]

    assert "/v1/chat/completions" in description
    assert "OpenAI" in description
