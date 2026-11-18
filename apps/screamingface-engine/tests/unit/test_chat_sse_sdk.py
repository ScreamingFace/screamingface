"""The openai SDK parses the streamed frames of chat/sse.py (prd/streaming.md, ST-4).

The SDK reads the bytes through an httpx.MockTransport, so the test is offline. The text cases
come from a seeded random.Random (plan D8: no hypothesis).

FEATURE: OpenAI-compatible Engine API, unit U5.
"""

from __future__ import annotations

import json
import random
from typing import Any

import httpx
import openai
import pytest
from openai import omit
from openai.types.chat import ChatCompletionChunk

from screamingface_engine.chat.result import ChatResult
from screamingface_engine.chat.sse import KEEP_ALIVE, ChunkMeta, error_event, frames
from screamingface_engine.chat.wire import ScreamingFaceInfo, ToolCall, Usage

META = ChunkMeta(id="chatcmpl-sdk", created=1_700_000_000, model="prov/a")
USAGE = Usage(prompt_tokens=30, completion_tokens=12, total_tokens=42)


def _info(result: ChatResult) -> ScreamingFaceInfo:
    """The screamingface object of the stream of one result."""

    return ScreamingFaceInfo(
        status=result.status,
        abstain_reason=result.abstain_reason,
        cost_usd="0.003",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )


def _calls() -> list[ToolCall]:
    """Two tool calls; the first one has a provider extra key."""

    return [
        ToolCall.model_validate(
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
                "extra_content": {"google": {"thought_signature": "sig"}},
            }
        ),
        ToolCall.model_validate(
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "get_time", "arguments": '{"zone":"CET"}'},
            }
        ),
    ]


def _random_text(rng: random.Random) -> str:
    """Printable ASCII with line breaks, quotes and non-ASCII characters."""

    alphabet = [chr(code) for code in range(0x20, 0x7F)]
    alphabet += ["\n", "\r", "\t", "é", "中", "😀", "\u2028"]
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40)))


def _random_cases(count: int) -> list[Any]:
    """Text answers with seeded random content."""

    rng = random.Random(20261118)
    return [
        pytest.param(
            ChatResult(status="answered", content=_random_text(rng), finish_reason="stop"),
            id=f"random-text-{index}",
        )
        for index in range(count)
    ]


CASES: list[Any] = [
    pytest.param(ChatResult(status="answered", content="Paris", finish_reason="stop"), id="text"),
    pytest.param(
        ChatResult(status="answered", content="one\ntwo\r\n", finish_reason="stop"),
        id="text-with-line-breaks",
    ),
    pytest.param(
        ChatResult(status="answered", content="café", finish_reason="stop"), id="text-accent"
    ),
    pytest.param(ChatResult(status="answered", content="ok 😀", finish_reason="stop"), id="emoji"),
    pytest.param(
        ChatResult(
            status="abstained", content="", abstain_reason="budget_refused", finish_reason="stop"
        ),
        id="abstained",
    ),
    pytest.param(
        ChatResult(status="refused", refusal="No.", finish_reason="content_filter"),
        id="refused",
    ),
    pytest.param(
        ChatResult(status="answered", tool_calls=_calls(), finish_reason="tool_calls"),
        id="tool-calls-without-content",
    ),
    pytest.param(
        ChatResult(
            status="answered",
            content="Let me check.",
            tool_calls=_calls(),
            finish_reason="tool_calls",
        ),
        id="tool-calls-with-content",
    ),
    *_random_cases(30),
]


def _payloads(raw: bytes) -> list[dict[str, Any] | str]:
    """Each data line of raw as its JSON object, or the string "[DONE]"."""

    payloads: list[dict[str, Any] | str] = []
    for block in raw.split(b"\n\n"):
        if block.startswith(b"data: "):
            body = block.removeprefix(b"data: ")
            payloads.append("[DONE]" if body == b"[DONE]" else json.loads(body))
    return payloads


def _sdk_chunks(raw: bytes, include_usage: bool) -> list[ChatCompletionChunk]:
    """Read raw as a streamed chat completion with the openai SDK."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=raw)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        client = openai.OpenAI(
            base_url="http://engine.invalid/v1",
            api_key="unused",
            http_client=http_client,
            max_retries=0,
        )
        stream = client.chat.completions.create(
            model="prov/a",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
            stream_options={"include_usage": True} if include_usage else omit,
        )
        return list(stream)
    finally:
        http_client.close()


def _tool_calls(
    chunks: list[ChatCompletionChunk],
) -> list[tuple[int | None, str | None, str | None, str | None]]:
    """The tool call fragments of a stream as (index, id, name, arguments)."""

    found: list[tuple[int | None, str | None, str | None, str | None]] = []
    for chunk in chunks:
        for choice in chunk.choices:
            for call in choice.delta.tool_calls or []:
                function = call.function
                name = function.name if function else None
                arguments = function.arguments if function else None
                found.append((call.index, call.id, name, arguments))
    return found


@pytest.mark.parametrize("include_usage", [False, True])
@pytest.mark.parametrize("result", CASES)
def test_openai_sdk_stream_parser_accepts_every_frame_sequence(
    result: ChatResult, include_usage: bool
) -> None:
    usage = USAGE if include_usage else None
    raw = KEEP_ALIVE + KEEP_ALIVE + b"".join(frames(result, META, _info(result), usage=usage))

    chunks = _sdk_chunks(raw, include_usage)

    assert all(isinstance(chunk, ChatCompletionChunk) for chunk in chunks)
    for payload in _payloads(raw):
        if payload != "[DONE]":
            ChatCompletionChunk.model_validate(payload)
    if result.status != "refused":
        text = "".join(chunk.choices[0].delta.content or "" for chunk in chunks if chunk.choices)
        assert text == result.content
    else:
        refusals = [chunk.choices[0].delta.refusal for chunk in chunks if chunk.choices]
        assert result.refusal in refusals
    expected_calls = [
        (index, call.id, call.function.name, call.function.arguments)
        for index, call in enumerate(result.tool_calls)
    ]
    assert _tool_calls(chunks) == expected_calls
    with_choices = [chunk for chunk in chunks if chunk.choices]
    assert with_choices[-1].choices[0].finish_reason == result.finish_reason
    if include_usage:
        assert chunks[-1].choices == []
        assert chunks[-1].usage is not None
        assert chunks[-1].usage.total_tokens == 42
    extra = chunks[-1].model_extra or {}
    assert extra["screamingface"]["status"] == result.status


def test_openai_sdk_raises_api_error_on_the_error_event() -> None:
    message = "the request did not finish in time; the run was stopped"
    raw = KEEP_ALIVE + error_event(message, "server_error", "timeout", should_retry=False)

    with pytest.raises(openai.APIError) as caught:
        _sdk_chunks(raw, include_usage=False)

    assert caught.value.code == "timeout"
    # SE-S6: the OpenAI SDK still raises on the event, and keeps the added retry key.
    assert caught.value.body == {
        "message": message,
        "type": "server_error",
        "code": "timeout",
        "should_retry": False,
    }
