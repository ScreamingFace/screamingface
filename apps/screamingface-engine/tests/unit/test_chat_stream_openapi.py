"""The OpenAPI entry of POST /v1/chat/completions shows the streamed answer.

FEATURE (OME chat endpoint, stream): `stream: true` answers with a server-sent event stream
(prd/streaming.md, contracts C2; review F8). The 200 entry lists both answers, and the request
body lists `stream_options.include_usage`.

WHY these assertions: an SDK user reads the 200 entry and the request body to learn the stream
shape. Both must name the stream and its end marker.
"""

from __future__ import annotations

from typing import Any

from screamingface_engine.app import create_app


def _op() -> dict[str, Any]:
    return create_app().openapi()["paths"]["/v1/chat/completions"]["post"]


def test_the_200_answer_lists_json_and_the_event_stream() -> None:
    """A consumer must see that `stream: true` answers with an event stream and its end."""
    content = _op()["responses"]["200"]["content"]

    assert {"application/json", "text/event-stream"} <= set(content)
    assert "[DONE]" in _op()["responses"]["200"]["description"]


def test_the_request_body_lists_stream_options_include_usage() -> None:
    """The request body documents `stream_options.include_usage` as a boolean."""
    schema = _op()["requestBody"]["content"]["application/json"]["schema"]

    assert schema["properties"]["stream_options"]["properties"]["include_usage"] == {
        "type": "boolean"
    }
