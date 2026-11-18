"""The server-sent event frames of a streamed chat completion (prd/streaming.md).

The stream is buffered: the run ends first, and then the whole answer comes as chunks. Each data
line is one JSON object on one line.

FEATURE: OpenAI-compatible Engine API, unit U5.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from screamingface_engine.chat.result import ChatResult
from screamingface_engine.chat.wire import ScreamingFaceInfo, Usage

__all__ = ["DONE", "KEEP_ALIVE", "ChunkMeta", "data_line", "error_event", "frames"]

KEEP_ALIVE: Final[bytes] = b": keep-alive\n\n"
DONE: Final[bytes] = b"data: [DONE]\n\n"
_CHUNK_OBJECT = "chat.completion.chunk"


@dataclass(frozen=True)
class ChunkMeta:
    """The fields that each chunk of one stream shares."""

    id: str
    created: int
    model: str


def data_line(payload: Mapping[str, Any]) -> bytes:
    """One SSE data line: the JSON of payload, then a blank line."""

    # WHY: ensure_ascii=True keeps every byte of a data line ASCII, so no client line splitter
    # can cut a JSON value. json already escapes the line breaks inside the values.
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return b"data: " + body.encode("ascii") + b"\n\n"


def error_event(message: str, type_: str, code: str) -> bytes:
    """The error event of a stream that already started (ST-S6): one data line, no [DONE]."""

    return data_line({"error": {"message": message, "type": type_, "code": code}})


def frames(
    result: ChatResult, meta: ChunkMeta, info: ScreamingFaceInfo, usage: Usage | None = None
) -> list[bytes]:
    """The whole answer as data lines, ending with [DONE].

    usage is given only when the client asked for stream_options.include_usage.
    """

    chunks: list[dict[str, Any]] = [_chunk(meta, [_choice(_first_delta(result), None)])]
    # INVARIANT: the tool calls come in ONE chunk, each with its full arguments string (ST-S2).
    if result.tool_calls:
        chunks.append(_chunk(meta, [_choice({"tool_calls": _tool_call_items(result)}, None)]))
    last = _chunk(meta, [_choice({}, result.finish_reason)])
    chunks.append(last)
    info_json = info.model_dump(mode="json")
    # INVARIANT: the screamingface object is only on the last chunk before [DONE] (ST-S3, ST-S4).
    if usage is None:
        last["screamingface"] = info_json
    else:
        tail = _chunk(meta, [])
        tail["usage"] = usage.model_dump(mode="json")
        tail["screamingface"] = info_json
        chunks.append(tail)
    return [*(data_line(chunk) for chunk in chunks), DONE]


def _chunk(meta: ChunkMeta, choices: list[dict[str, Any]]) -> dict[str, Any]:
    """One chunk object, with the fields that all chunks of a stream share."""

    return {
        "id": meta.id,
        "object": _CHUNK_OBJECT,
        "created": meta.created,
        "model": meta.model,
        "choices": choices,
    }


def _choice(delta: dict[str, Any], finish_reason: str | None) -> dict[str, Any]:
    """The one choice of a chunk."""

    return {"index": 0, "delta": delta, "finish_reason": finish_reason}


def _first_delta(result: ChatResult) -> dict[str, Any]:
    """The delta of the first chunk: the role, then the content or the refusal."""

    delta: dict[str, Any] = {"role": "assistant"}
    if result.status == "refused":
        # WHY: the refusal keys are always present for a refused result, as in the non-streamed
        # message of rest/chat_answer.py.
        delta["content"] = None
        delta["refusal"] = result.refusal
    elif result.content or not result.tool_calls:
        delta["content"] = result.content
    return delta


def _tool_call_items(result: ChatResult) -> list[dict[str, Any]]:
    """Each tool call as it was sent, with its index set last."""

    items: list[dict[str, Any]] = []
    for index, call in enumerate(result.tool_calls):
        item = call.model_dump(mode="json")
        item["index"] = index
        items.append(item)
    return items
