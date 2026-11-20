"""The OpenAPI entry of POST /v1/chat/completions.

The route declares no body parameter (it reads the body with a running cap), so its request
body is documented here through `openapi_extra`. Each error answer is the OpenAI envelope.
The 200 entry lists both answers: the JSON completion and the streamed event answer.
"""

from __future__ import annotations

from typing import Any

__all__ = ["CHAT_RESPONSES", "CHAT_TAG", "REQUEST_BODY"]

CHAT_TAG = "Chat"

_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["error"],
    "properties": {
        "error": {
            "type": "object",
            "required": ["message", "type", "param", "code"],
            "properties": {
                "message": {"type": "string"},
                "type": {"type": "string"},
                "param": {"type": ["string", "null"]},
                "code": {"type": ["string", "null"]},
            },
        }
    },
}


def _error(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"schema": _ERROR_SCHEMA}},
    }


REQUEST_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["model", "messages"],
                    "properties": {
                        "model": {
                            "type": "string",
                            "description": "A Candidate URL4, or a model id of GET /v1/models.",
                        },
                        "messages": {"type": "array", "items": {"type": "object"}},
                        "tools": {"type": "array", "items": {"type": "object"}},
                        "stream": {"type": "boolean"},
                        "stream_options": {
                            "type": "object",
                            "description": "With `stream: true`: `include_usage` adds one usage "
                            "chunk before `[DONE]`.",
                            "properties": {"include_usage": {"type": "boolean"}},
                        },
                    },
                    "additionalProperties": True,
                }
            }
        },
    }
}

CHAT_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "The chat completion as JSON, with an extra `screamingface` object. With "
            "`stream: true`, a `text/event-stream` of `chat.completion.chunk` data lines and "
            "`: keep-alive` comments that ends with `data: [DONE]`; an error after the stream "
            'starts is one `{"error": ...}` data line and no `[DONE]`.'
        ),
        "content": {
            "application/json": {"schema": {"type": "object"}},
            "text/event-stream": {"schema": {"type": "string"}},
        },
    },
    400: _error(
        "`invalid_request`, `unsupported_parameter`, `unsupported_content`, "
        "`recipe_invalid`, `recipe_not_supported`, `final_step_not_model` or "
        "`model_does_not_support_tools`."
    ),
    401: _error("`identity_required`: no verified caller identity."),
    404: _error("`model_not_found`: the model id is not known."),
    413: _error("`request_too_large`: the body, the input record or `model` is too large."),
    415: _error("`unsupported_media_type`: the media type is not `application/json`."),
    422: _error("`fail_closed`: the recipe failed closed."),
    429: _error("`overloaded`, with `Retry-After`."),
    500: _error("`chat_input_unavailable` or `chat_input_invalid`."),
    502: _error("The run failed, or its result could not be read."),
    503: _error(
        "`chat_unavailable`, `catalog_unavailable`, `queue_unavailable`, `run_failed`, "
        "`worker_draining` or `server_restarting`. A retryable `run_failed`, "
        "`worker_draining` and `server_restarting` send `Retry-After: 5`."
    ),
    504: _error("`timeout`: the run did not end in time and was stopped."),
}
