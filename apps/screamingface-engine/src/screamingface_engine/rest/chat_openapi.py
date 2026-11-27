"""The OpenAPI entry of POST /v1/chat/completions.

The route declares no body parameter (it reads the body with a running cap), so its request
body is documented here through `openapi_extra`. Each error answer is the OpenAI envelope.
The 200 entry lists both answers: the JSON completion and the streamed event answer.

INVARIANT (RR-S15): each status and body code that the route can answer is declared here.
`tests/unit/test_chat_review2_openapi.py` reads them from the route code and compares.
"""

from __future__ import annotations

from typing import Any, cast

from screamingface_engine.chat.wire import ChatCompletionResponse

__all__ = [
    "ACCESS_SCHEME",
    "CHAT_PATH",
    "CHAT_RESPONSES",
    "CHAT_TAG",
    "REQUEST_BODY",
    "set_chat_security",
]

CHAT_TAG = "Chat"
CHAT_PATH = "/v1/chat/completions"

# WHY this scheme: a hosted Engine is behind Cloudflare Access. The client sends its Access token
# in `Cf-Access-Token` (public-docs/src/snippets/openai-chat/openai_sdk.py, the SDK
# `_access/auth.py`); the edge verifies it and gives the App the verified `X-User-Email`, which
# `rest/runs_boundary.request_caller` reads. A client cannot set that header, so the scheme names
# the header that the client sends. The chat route never reads the `URL4-Capability` JWT.
ACCESS_SCHEME = "CloudflareAccess"
_ACCESS_SECURITY_SCHEME: dict[str, Any] = {
    "type": "apiKey",
    "in": "header",
    "name": "Cf-Access-Token",
    "description": (
        "The Cloudflare Access token of a hosted Engine (`cloudflared access token`). Local "
        "mode needs no credential."
    ),
}

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


_SHOULD_RETRY_HEADER: dict[str, Any] = {
    "description": "`true` when the same request can succeed when sent again, else `false`.",
    "schema": {"type": "string", "enum": ["true", "false"]},
}
_RETRY_AFTER_HEADER: dict[str, Any] = {
    "description": "The seconds to wait before the next try. Only a retryable answer has it.",
    "schema": {"type": "integer", "minimum": 0},
}


def _error(description: str, *, retry_after: bool = False) -> dict[str, Any]:
    headers = {"x-should-retry": _SHOULD_RETRY_HEADER}
    if retry_after:
        headers["Retry-After"] = _RETRY_AFTER_HEADER
    return {
        "description": description,
        "headers": headers,
        "content": {"application/json": {"schema": _ERROR_SCHEMA}},
    }


def _inline(node: object, defs: dict[str, Any]) -> Any:
    """A copy of a pydantic JSON schema with each `$ref` replaced by its definition.

    WHY: a `#/$defs/...` reference inside a response of the OpenAPI document resolves against
    the document root, where no `$defs` exist. The answer models are not recursive.
    """
    if isinstance(node, list):
        return [_inline(item, defs) for item in cast(list[object], node)]
    if isinstance(node, dict):
        return _inline_mapping(cast(dict[str, object], node), defs)
    return node


def _inline_mapping(mapping: dict[str, object], defs: dict[str, Any]) -> Any:
    ref = mapping.get("$ref")
    if isinstance(ref, str):
        return _inline(defs[ref.rsplit("/", 1)[-1]], defs)
    return {key: _inline(value, defs) for key, value in mapping.items() if key != "$defs"}


def _object_branch(schema: dict[str, Any]) -> dict[str, Any]:
    branches = cast(list[dict[str, Any]], schema.get("anyOf", [schema]))
    return next(branch for branch in branches if branch.get("type") == "object")


def _completion_schema() -> dict[str, Any]:
    """The JSON answer, from the model that the route dumps (RR-S12, RR-S14).

    The two keys that the route leaves out when they carry nothing are never `null`, so they
    are shown with their sent shape.
    """
    raw = ChatCompletionResponse.model_json_schema(mode="serialization")
    schema = cast(dict[str, Any], _inline(raw, cast(dict[str, Any], raw.get("$defs", {}))))
    info = schema["properties"]["screamingface"]["properties"]
    info["ignored_parameters"] = {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
        "description": (
            "The sorted names of the top-level request fields that the Engine ignored. Absent "
            "when the Engine ignored no field."
        ),
    }
    final_step = _object_branch(info["final_step"])
    final_step["properties"]["cached"] = {
        "type": "boolean",
        "const": True,
        "description": "`true` when the gateway cache answered the final step. Absent on a miss.",
    }
    return schema


def set_chat_security(schema: dict[str, Any], *, hosted: bool) -> None:
    """Hosted mode: the chat operation names the Access header scheme (RR-S15).

    The chat operation is found by its path, `CHAT_PATH`, so no other operation gets the scheme.
    Local mode is single-user (`rest/runs_boundary.request_caller`), so the operation keeps no
    security requirement.
    """
    if not hosted:
        return
    schema.setdefault("components", {}).setdefault("securitySchemes", {})[ACCESS_SCHEME] = dict(
        _ACCESS_SECURITY_SCHEME
    )
    operation = cast(dict[str, Any] | None, schema.get("paths", {}).get(CHAT_PATH, {}).get("post"))
    if operation is not None:
        operation["security"] = [{ACCESS_SCHEME: []}]


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
            "application/json": {"schema": _completion_schema()},
            "text/event-stream": {"schema": {"type": "string"}},
        },
    },
    400: _error(
        "`invalid_request` (also `n` below 1), `unsupported_parameter`, "
        "`tools_not_available`, `unsupported_content`, or a recipe code: `recipe_invalid`, "
        "`recipe_not_supported`, `final_step_not_model` or `model_does_not_support_tools`."
    ),
    401: _error("`identity_required`: a hosted request has no verified caller identity."),
    404: _error("`model_not_found`: the model id is not known."),
    408: _error(
        "`request_timeout`: the full body did not arrive in 30 s from the start of the read. "
        "When a body above 1,000,000 bytes gets a parse place, the limit changes to 30 s from "
        "that time."
    ),
    409: _error("`internal_error`: the run could not start, for example a start conflict."),
    413: _error("`request_too_large`: the body, the input record or `model` is too large."),
    415: _error("`unsupported_media_type`: the media type is not `application/json`."),
    422: _error("`fail_closed`: the recipe failed closed."),
    429: _error(
        "`overloaded`: the server is at capacity, or all parse places of a large body are in "
        "use. Sends `Retry-After`.",
        retry_after=True,
    ),
    500: _error(
        "`internal_error`: an error that the route did not expect. `chat_input_unavailable`: "
        "the input record of the run is gone (permanent). `chat_input_invalid`: the input "
        "record of the run is not valid."
    ),
    502: _error(
        "`result_unavailable`, `result_invalid`, `result_too_large` (the result is larger "
        "than 8 MiB), `final_step_ambiguous`, `internal_error`, or a run error code that the "
        "Engine vouches for."
    ),
    503: _error(
        "`chat_unavailable`, `catalog_unavailable`, `queue_unavailable`, `run_failed`, "
        "`worker_draining`, `server_restarting`, `chat_input_unavailable` (a short outage "
        "of the input store), or `internal_error` (no run scheduler is set up). Each answer "
        "with `x-should-retry: true` sends `Retry-After`: 5 s for `run_failed`, "
        "`worker_draining`, `server_restarting`, `chat_input_unavailable`, "
        "`catalog_unavailable` and `queue_unavailable`.",
        retry_after=True,
    ),
    504: _error("`timeout`: the run did not end in time and was stopped."),
}
