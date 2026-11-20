"""The SSE frames of a streamed chat completion (prd/streaming.md, ST-1 to ST-3, ST-12, ST-13).

The frames are plain bytes built by chat/sse.py. Each test reads them back as JSON, so the tests
pin the shape of the chunks and the order of the lines. The stream is buffered: the whole answer
comes as chunks after the run ends.

FEATURE: OpenAI-compatible Engine API, unit U5.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from screamingface_engine.chat.result import ChatResult
from screamingface_engine.chat.sse import DONE, ChunkMeta, error_event, frames
from screamingface_engine.chat.wire import ChatStatus, ScreamingFaceInfo, ToolCall, Usage

META = ChunkMeta(id="chatcmpl-abc", created=1_700_000_000, model="prov/a")
USAGE = Usage(prompt_tokens=30, completion_tokens=12, total_tokens=42)


def _info(status: ChatStatus = "answered", **kw: Any) -> ScreamingFaceInfo:
    """The screamingface object of a test stream."""

    return ScreamingFaceInfo(
        status=status, cost_usd="0.003", trace_id="4bf92f3577b34da6a3ce929d0e0e4736", **kw
    )


def _payloads(lines: list[bytes]) -> list[dict[str, Any] | str]:
    """Each data line as its JSON object, or the string "[DONE]"; each line is one frame."""

    payloads: list[dict[str, Any] | str] = []
    for line in lines:
        assert line.startswith(b"data: ")
        assert line.endswith(b"\n\n")
        body = line.removeprefix(b"data: ").removesuffix(b"\n\n")
        assert b"\n" not in body
        assert b"\r" not in body
        payloads.append("[DONE]" if body == b"[DONE]" else json.loads(body))
    return payloads


def _chunks(lines: list[bytes]) -> list[dict[str, Any]]:
    """The chunk objects of a stream, after the check that [DONE] ends it."""

    assert lines[-1] == DONE
    return [payload for payload in _payloads(lines) if isinstance(payload, dict)]


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


def test_text_result_frames_as_role_content_chunk_finish_chunk_done() -> None:
    result = ChatResult(status="answered", content="Paris", finish_reason="stop")

    lines = frames(result, META, _info())

    assert len(lines) == 3
    assert lines[-1] == DONE
    chunks = _chunks(lines)
    assert chunks[0]["choices"] == [
        {"index": 0, "delta": {"role": "assistant", "content": "Paris"}, "finish_reason": None}
    ]
    assert chunks[1]["choices"][0] == {"index": 0, "delta": {}, "finish_reason": "stop"}
    assert chunks[1]["screamingface"] == _info().model_dump(mode="json")
    assert "screamingface" not in chunks[0]
    assert all("usage" not in chunk for chunk in chunks)
    for chunk in chunks:
        assert chunk["id"] == META.id
        assert chunk["object"] == "chat.completion.chunk"
        assert chunk["created"] == META.created
        assert chunk["model"] == META.model


def test_tool_calls_frame_with_index_id_name_and_full_arguments() -> None:
    for content in ("", "Let me check."):
        result = ChatResult(
            status="answered", content=content, tool_calls=_calls(), finish_reason="tool_calls"
        )

        lines = frames(result, META, _info())

        assert len(lines) == 4
        chunks = _chunks(lines)
        expected_first = (
            {"role": "assistant", "content": content} if content else {"role": "assistant"}
        )
        assert chunks[0]["choices"][0]["delta"] == expected_first
        assert chunks[1]["choices"][0]["delta"] == {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
                    "extra_content": {"google": {"thought_signature": "sig"}},
                },
                {
                    "index": 1,
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "get_time", "arguments": '{"zone":"CET"}'},
                },
            ]
        }
        assert chunks[2]["choices"][0]["finish_reason"] == "tool_calls"


def test_include_usage_adds_usage_chunk_with_empty_choices() -> None:
    result = ChatResult(status="answered", content="Paris", finish_reason="stop")

    lines = frames(result, META, _info(), usage=USAGE)

    assert len(lines) == 4
    assert lines[-1] == DONE
    chunks = _chunks(lines)
    assert "screamingface" not in chunks[1]
    assert "usage" not in chunks[1]
    assert chunks[2]["choices"] == []
    assert chunks[2]["usage"] == USAGE.model_dump(mode="json")
    assert chunks[2]["screamingface"] == _info().model_dump(mode="json")


def test_refusal_frames_with_delta_refusal_and_content_filter() -> None:
    result = ChatResult(
        status="refused", refusal="I can't help with that.", finish_reason="content_filter"
    )

    chunks = _chunks(frames(result, META, _info("refused")))

    assert chunks[0]["choices"][0]["delta"] == {
        "role": "assistant",
        "content": None,
        "refusal": "I can't help with that.",
    }
    assert chunks[-1]["choices"][0]["finish_reason"] == "content_filter"


@pytest.mark.parametrize("usage", [None, USAGE])
def test_abstained_result_frames_with_status_in_last_chunk(usage: Usage | None) -> None:
    result = ChatResult(
        status="abstained", content="", abstain_reason="budget_refused", finish_reason="stop"
    )
    info = _info("abstained", abstain_reason="budget_refused")

    chunks = _chunks(frames(result, META, info, usage=usage))

    assert chunks[0]["choices"][0]["delta"]["content"] == ""
    assert chunks[1]["choices"][0]["finish_reason"] == "stop"
    assert chunks[-1]["screamingface"]["status"] == "abstained"
    assert chunks[-1]["screamingface"]["abstain_reason"] == "budget_refused"


def test_error_event_is_one_data_line_with_message_type_and_code() -> None:
    assert error_event("the run failed", "server_error", "run_failed") == (
        b'data: {"error":{"message":"the run failed","type":"server_error","code":"run_failed"}}'
        b"\n\n"
    )


def test_data_lines_are_ascii_and_keep_the_text() -> None:
    text = "a\nb\r\nc é 😀"
    result = ChatResult(status="answered", content=text, finish_reason="stop")

    lines = frames(result, META, _info())

    assert all(line.isascii() for line in lines)
    assert _chunks(lines)[0]["choices"][0]["delta"]["content"] == text
