"""Wire bytes of the Engine chat stream for the frame reader tests.

The helpers copy apps/screamingface-engine/src/screamingface_engine/chat/sse.py, so the tests read
the same wire that the Engine sends.
AIDEV-NOTE: this is a hand copy, and no test links it to the Engine: the SDK tests cannot import
the Engine package. If chat/sse.py changes the frame order or a key, change this file too. The
integration test MI-28 (prd/model-inference.md section 5) is the only check that reads the real
Engine wire.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

KEEP_ALIVE = b": keep-alive\n\n"
DONE_LINE = b"data: [DONE]\n\n"
META: dict[str, Any] = {
    "id": "chatcmpl-1",
    "object": "chat.completion.chunk",
    "created": 1700000000,
    "model": "openrouter/a",
}
USAGE: dict[str, Any] = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
ZERO_USAGE: dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
TOOL_CALL: dict[str, Any] = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
}
SECOND_CALL: dict[str, Any] = {
    "id": "call_2",
    "type": "function",
    "function": {"name": "get_time", "arguments": "{}"},
}


def info(**changes: Any) -> dict[str, Any]:
    """The screamingface object of a reply, with the changed keys."""

    base: dict[str, Any] = {
        "status": "answered",
        "abstain_reason": None,
        "cost_usd": "0.0012",
        "trace_id": TRACE_ID,
        "final_step": {"binding": "model_1", "model": "openrouter/a", "usage": dict(USAGE)},
    }
    return {**base, **changes}


def data_line(payload: Any) -> bytes:
    """One SSE data line, as the Engine sends it."""

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return b"data: " + body + b"\n\n"


def error_line(**error: Any) -> bytes:
    """The error event of a stream that already started."""

    return data_line({"error": error})


def chunk(choices: list[Any], **extra: Any) -> dict[str, Any]:
    """One chunk object, with the fields that all chunks of a stream share."""

    return {**META, "choices": choices, **extra}


def choice(delta: dict[str, Any], finish_reason: str | None = None) -> dict[str, Any]:
    """The one choice of a chunk."""

    return {"index": 0, "delta": delta, "finish_reason": finish_reason}


def tool_chunk(*calls: dict[str, Any]) -> dict[str, Any]:
    """The chunk that carries all the tool calls at once, each with its index."""

    items = [{**call, "index": index} for index, call in enumerate(calls)]
    return chunk([choice({"tool_calls": items})])


def engine_stream(
    first_delta: dict[str, Any],
    finish_reason: str,
    *,
    tool_calls: tuple[dict[str, Any], ...] = (),
    usage: dict[str, Any] | None = None,
    screamingface: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The chunk payloads that the Engine sends with include_usage, in order."""

    payloads: list[dict[str, Any]] = [chunk([choice(first_delta)])]
    if tool_calls:
        payloads.append(tool_chunk(*tool_calls))
    payloads.append(chunk([choice({}, finish_reason)]))
    payloads.append(chunk([], usage=usage or USAGE, screamingface=screamingface or info()))
    return payloads


def wire(payloads: list[Any], *, done: bool = True) -> bytes:
    """The bytes of a whole stream: the data lines, then [DONE] when done is True."""

    return b"".join(data_line(payload) for payload in payloads) + (DONE_LINE if done else b"")


def message(
    content: str | None,
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    refusal: str | None = None,
) -> dict[str, Any]:
    """The expected message object of a plain reply."""

    return {"role": "assistant", "content": content, "tool_calls": tool_calls, "refusal": refusal}


def sse_lines(body: bytes) -> list[str]:
    """The lines of an SSE body, read as the transport reads them (httpx Response.iter_lines)."""

    return list(httpx.Response(200, content=body).iter_lines())
