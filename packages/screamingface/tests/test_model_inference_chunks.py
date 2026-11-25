"""The shared chunk steps of the chat transport (contracts C1.4, C2.1, C2.3), unit U5."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from _chat_frames import TOOL_CALL, engine_stream

from screamingface._inference.chunks import (
    afailed_chunks,
    awith_first,
    chunk_of,
    completion_of,
    failed_chunks,
    with_first,
)
from screamingface._inference.error_map import outcome_unknown
from screamingface._inference.frames import StreamError, chunk_from_payload
from screamingface.chat_completion import ChatCompletionChunk
from screamingface.errors import ExecutionError

TEXT = engine_stream({"role": "assistant", "content": "Hi"}, "stop")
TOOLS = engine_stream({"role": "assistant"}, "tool_calls", tool_calls=(TOOL_CALL,))


def chunks(payloads: list[dict[str, Any]]) -> list[ChatCompletionChunk]:
    return [chunk_from_payload(p) for p in payloads]


async def agen(items: list[ChatCompletionChunk]) -> AsyncIterator[ChatCompletionChunk]:
    for item in items:
        yield item


@pytest.mark.parametrize("payloads", [TEXT, TOOLS], ids=["text", "tools"])
def test_with_first_gives_the_first_chunk_then_the_rest(payloads: list[dict[str, Any]]) -> None:
    wire = chunks(payloads)

    assert list(with_first(wire[0], wire[1:])) == wire


@pytest.mark.asyncio
@pytest.mark.parametrize("payloads", [TEXT, TOOLS], ids=["text", "tools"])
async def test_awith_first_matches_with_first(payloads: list[dict[str, Any]]) -> None:
    wire = chunks(payloads)

    assert [c async for c in awith_first(wire[0], agen(wire[1:]))] == wire


def test_chunk_of_gives_the_chunk_of_a_data_object() -> None:
    assert chunk_of(TEXT[0], "t1") == chunk_from_payload(TEXT[0])


def test_chunk_of_raises_the_mapped_error_event() -> None:
    event = StreamError(
        message="restart",
        type="server_error",
        code="server_restarting",
        should_retry=True,
        retry_after=5,
    )

    with pytest.raises(ExecutionError) as e:
        chunk_of(event, "t1")

    assert (e.value.code, e.value.permanent, e.value.details, e.value.trace_id) == (
        "server_restarting",
        False,
        {"retry_after": 5},
        "t1",
    )


def test_completion_of_builds_the_reply() -> None:
    assert completion_of(chunks(TEXT), "t1").text == "Hi"


def test_completion_of_maps_a_wrong_shape_to_invalid_response() -> None:
    with pytest.raises(ExecutionError) as e:
        completion_of(chunks(TEXT[:1]), "t1")

    assert e.value.code == "invalid_response"
    assert e.value.details == {"reason": "wrong_shape"}
    assert e.value.trace_id == "t1"


def test_failed_chunks_raises_at_the_first_next() -> None:
    gen = failed_chunks(outcome_unknown("t1"))

    with pytest.raises(ExecutionError) as e:
        next(gen)

    assert e.value.code == "inference_outcome_unknown"


@pytest.mark.asyncio
async def test_afailed_chunks_raises_at_the_first_anext() -> None:
    with pytest.raises(ExecutionError) as e:
        await anext(afailed_chunks(outcome_unknown("t1")))

    assert e.value.code == "inference_outcome_unknown"
