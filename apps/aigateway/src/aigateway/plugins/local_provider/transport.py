from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import HTTPException

from aigateway.core.json_bounds import assert_bounded_json

_MAX_RESPONSE_BYTES = 1_000_000
_MAX_JSON_DEPTH = 16
_MAX_JSON_NODES = 50_000


def _error(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=502, detail={"code": code, "message": message})


def _upstream_error(response: httpx.Response) -> HTTPException:
    status = response.status_code
    public_status = status if 400 <= status < 500 or status in {503, 529} else 502
    retry_after = response.headers.get("retry-after")
    headers = (
        {"Retry-After": retry_after}
        if retry_after is not None and retry_after.isascii() and retry_after.isdecimal()
        else None
    )
    # INVARIANT: status and numeric retry timing may drive shared retry policy;
    # upstream bodies and arbitrary headers never cross this boundary.
    return HTTPException(
        status_code=public_status,
        detail={
            "code": "provider_error",
            "message": "The local model server returned an error.",
        },
        headers=headers,
    )


async def _read_bounded(response: httpx.Response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
            raise _error("provider_error", "The local model response is invalid.")
        body.extend(chunk)
    return bytes(body)


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def _decode_completion(body: bytes) -> dict[str, Any]:
    try:
        result = json.loads(body, parse_constant=_reject_non_finite)
        assert_bounded_json(
            result,
            max_depth=_MAX_JSON_DEPTH,
            max_nodes=_MAX_JSON_NODES,
            require_finite=True,
        )
    except (ValueError, RecursionError):
        raise _error("provider_error", "The local model response is invalid.") from None
    if not isinstance(result, dict):
        raise _error("provider_error", "The local model response is invalid.")
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _error("provider_error", "The local model response is invalid.")
    for choice in choices:
        if not isinstance(choice, dict):
            raise _error("provider_error", "The local model response is invalid.")
        message = choice.get("message")
        if not _is_openai_message(message):
            raise _error("provider_error", "The local model response is invalid.")
    return result


def _is_openai_message(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    # WHY: reasoning models and tool calls legitimately return null/empty content. The
    # Engine owns outcome policy (token cap vs reasoning-only vs tool turn); this boundary
    # validates the wire shape without erasing that evidence.
    content = value.get("content")
    reasoning = value.get("reasoning")
    reasoning_content = value.get("reasoning_content")
    tool_calls = value.get("tool_calls")
    if not (
        (content is None or isinstance(content, str))
        and (reasoning is None or isinstance(reasoning, str))
        and (reasoning_content is None or isinstance(reasoning_content, str))
    ):
        return False
    valid_tools = _valid_tool_calls(tool_calls)
    # WHY: vLLM <=0.11 serializes an unused default_factory as `tool_calls: []`.
    # Empty and absent carry the same OpenAI-compatible meaning; malformed non-empty
    # collections still fail the strict shape check below.
    if tool_calls not in (None, []) and not valid_tools:
        return False
    has_reasoning = any(
        isinstance(candidate, str) and bool(candidate.strip())
        for candidate in (reasoning, reasoning_content)
    )
    return "content" in value or has_reasoning or valid_tools


def _valid_tool_calls(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for call in value:
        if not isinstance(call, dict) or call.get("type") != "function":
            return False
        if not isinstance(call.get("id"), str) or not call["id"]:
            return False
        function = call.get("function")
        if not isinstance(function, dict):
            return False
        if not isinstance(function.get("name"), str) or not function["name"]:
            return False
        if not isinstance(function.get("arguments"), str):
            return False
    return True


async def post_chat_completion(
    base_url: str,
    payload: dict[str, Any],
    *,
    transport: httpx.AsyncBaseTransport | None,
) -> dict[str, Any]:
    try:
        # INVARIANT: core.admission is the one wall-clock authority. A second HTTPX phase
        # timeout would silently cut the Engine/operator budget (up to 1800 s) back to 30 s.
        async with httpx.AsyncClient(
            base_url=base_url,
            follow_redirects=False,
            trust_env=False,
            timeout=None,
            transport=transport,
        ) as client:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise _upstream_error(response)
                content_type = response.headers.get("content-type", "")
                if content_type.split(";", 1)[0].strip().lower() != "application/json":
                    raise _error("provider_error", "The local model response is invalid.")
                return _decode_completion(await _read_bounded(response))
    except HTTPException:
        raise
    except (TimeoutError, httpx.HTTPError):
        raise _error("provider_unavailable", "The local model server is unavailable.") from None
