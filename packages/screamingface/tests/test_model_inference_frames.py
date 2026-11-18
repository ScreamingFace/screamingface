"""MI-4: the frame reader builds the reply of the plain route from the Engine stream.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C2.3, the SE-5
rule).
INVARIANT: no transport: bytes in, typed values out.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
from _chat_frames import (
    DONE_LINE,
    KEEP_ALIVE,
    SECOND_CALL,
    TOOL_CALL,
    TRACE_ID,
    USAGE,
    ZERO_USAGE,
    choice,
    chunk,
    data_line,
    engine_stream,
    info,
    message,
    wire,
)

from screamingface._inference.frames import (
    DONE,
    build_completion,
    completion_from_lines,
    event_from_line,
    lines_from_bytes,
    read_chunks,
)
from screamingface.chat_completion import ChatCompletion, ChatCompletionChunk, ChatToolCall

TEXT = engine_stream({"role": "assistant", "content": "Hello"}, "stop")
NO_TEXT_CALLS = engine_stream({"role": "assistant"}, "tool_calls", tool_calls=(TOOL_CALL,))
WITH_TEXT_CALLS = engine_stream(
    {"role": "assistant", "content": "Let me check."}, "tool_calls", tool_calls=(TOOL_CALL,)
)

ROWS: list[tuple[str, list[Any], dict[str, Any], str, dict[str, Any], dict[str, Any]]] = [
    ("text", TEXT, message("Hello"), "stop", USAGE, info()),
    # WHY: MI-4 "no usage frame" (prd/model-inference.md section 5) is a run that gave no cost
    # record: usage 0/0/0 and cost_usd null (contracts C1.3; the Engine SE-5 row "text-no-cost").
    # A stream with no usage chunk is a wrong shape (MI-5 row "no-usage-chunk").
    (
        "no-cost-record",
        engine_stream(
            {"role": "assistant", "content": "Hello"},
            "stop",
            usage=ZERO_USAGE,
            screamingface=info(cost_usd=None),
        ),
        message("Hello"),
        "stop",
        ZERO_USAGE,
        info(cost_usd=None),
    ),
    (
        "refusal",
        engine_stream(
            {"role": "assistant", "content": None, "refusal": "no"},
            "content_filter",
            screamingface=info(status="refused", final_step=None),
        ),
        message(None, refusal="no"),
        "content_filter",
        USAGE,
        info(status="refused", final_step=None),
    ),
    (
        "tool-calls-with-text",
        WITH_TEXT_CALLS,
        message("Let me check.", tool_calls=[TOOL_CALL]),
        "tool_calls",
        USAGE,
        info(),
    ),
    (
        "tool-calls-no-text",
        NO_TEXT_CALLS,
        message(None, tool_calls=[TOOL_CALL]),
        "tool_calls",
        USAGE,
        info(),
    ),
    (
        "abstained",
        engine_stream(
            {"role": "assistant", "content": ""},
            "stop",
            screamingface=info(status="abstained", abstain_reason="budget_refused"),
        ),
        message(""),
        "stop",
        USAGE,
        info(status="abstained", abstain_reason="budget_refused"),
    ),
]


def _reply(body: bytes) -> ChatCompletion:
    result = completion_from_lines(lines_from_bytes(body))
    assert isinstance(result, ChatCompletion)
    return result


def _chunks(body: bytes) -> list[ChatCompletionChunk]:
    items: list[ChatCompletionChunk] = []
    for item in read_chunks(lines_from_bytes(body)):
        assert isinstance(item, ChatCompletionChunk)
        items.append(item)
    return items


@pytest.mark.parametrize(
    ("name", "payloads", "expected", "finish_reason", "usage", "screamingface"),
    ROWS,
    ids=[row[0] for row in ROWS],
)
def test_frames_build_the_reply_of_the_plain_route(
    name: str,
    payloads: list[Any],
    expected: dict[str, Any],
    finish_reason: str,
    usage: dict[str, Any],
    screamingface: dict[str, Any],
) -> None:
    """MI-4: each row gives the reply that the plain route gives for the same run."""

    assert _reply(wire(payloads)).to_dict() == {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "openrouter/a",
        "choices": [{"index": 0, "message": expected, "finish_reason": finish_reason}],
        "usage": usage,
        "screamingface": screamingface,
    }


def test_reply_short_forms_read_the_built_reply() -> None:
    """MI-4 / C1.3: the short forms of the reply read the built values."""

    text = _reply(wire(TEXT))
    assert text.text == "Hello"
    assert text.cost_usd == Decimal("0.0012")
    assert text.trace_id == TRACE_ID
    assert text.tool_calls is None

    no_text = _reply(wire(NO_TEXT_CALLS))
    assert no_text.text is None
    tool_calls = no_text.tool_calls
    assert tool_calls is not None
    assert isinstance(tool_calls[0], ChatToolCall)
    assert tool_calls[0].function.arguments == '{"city":"Paris"}'


def test_tool_calls_come_in_index_order() -> None:
    """MI-4 / C2.3: the tool calls are sorted by index, and the index key is removed."""

    payloads = [
        chunk([choice({"role": "assistant"})]),
        chunk([choice({"tool_calls": [{**SECOND_CALL, "index": 1}, {**TOOL_CALL, "index": 0}]})]),
        chunk([choice({}, "tool_calls")]),
        chunk([], usage=USAGE, screamingface=info()),
    ]
    reply = _reply(wire(payloads))
    assert reply.tool_calls is not None
    assert tuple(call.id for call in reply.tool_calls) == ("call_1", "call_2")

    body: Any = reply.to_dict()
    assert body["choices"][0]["message"]["tool_calls"] == [TOOL_CALL, SECOND_CALL]


def test_keep_alive_lines_are_dropped() -> None:
    """MI-4 / C2.3 step 1: the keep-alive comment lines give the same reply."""

    body = KEEP_ALIVE + KEEP_ALIVE + KEEP_ALIVE.join(data_line(p) for p in TEXT) + DONE_LINE
    assert _reply(body).to_dict() == _reply(wire(TEXT)).to_dict()


@pytest.mark.parametrize("line", [": keep-alive", ":", "", "event: ping", "id: 7", "retry: 1000"])
def test_keep_alive_and_blank_lines_give_no_event(line: str) -> None:
    """MI-4: a line that is not a data line gives no event."""

    assert event_from_line(line) is None


def test_done_line_is_the_done_event() -> None:
    """MI-4: the [DONE] line is the done event, with or without the space after the colon."""

    assert event_from_line("data: [DONE]") is DONE
    assert event_from_line("data:[DONE]") is DONE


def test_a_data_line_with_no_space_is_read() -> None:
    """MI-4: the space after the colon of a data line is optional."""

    assert event_from_line('data:{"a":1}') == {"a": 1}


def test_crlf_line_ends_give_the_same_reply() -> None:
    """MI-4: CRLF line ends give the same reply as LF line ends."""

    crlf = wire(TEXT).replace(b"\n", b"\r\n")
    assert _reply(crlf).to_dict() == _reply(wire(TEXT)).to_dict()


def test_unknown_keys_are_ignored() -> None:
    """MI-4 / forward compatible: keys that the SDK does not know change nothing."""

    extra = copy.deepcopy(WITH_TEXT_CALLS)
    for payload in extra:
        payload["system_fingerprint"] = "fp_1"
        for item in payload["choices"]:
            item["logprobs"] = None
    extra[0]["choices"][0]["delta"]["annotations"] = []
    extra[1]["choices"][0]["delta"]["tool_calls"][0]["extra"] = 1
    extra[3]["usage"]["prompt_tokens_details"] = {"cached_tokens": 0}
    extra[3]["screamingface"]["new_key"] = 1
    extra[3]["screamingface"]["final_step"]["extra"] = True

    assert _reply(wire(extra)).to_dict() == _reply(wire(WITH_TEXT_CALLS)).to_dict()


def test_read_chunks_gives_the_engine_chunks_in_order() -> None:
    """MI-4 / C2.3: read_chunks gives the four chunks of a tool-call run, in order."""

    chunks = _chunks(wire(WITH_TEXT_CALLS))
    assert len(chunks) == 4
    assert chunks[0].text == "Let me check."

    calls = chunks[1].choices[0].delta.tool_calls
    assert calls is not None
    assert calls[0].index == 0
    body: Any = chunks[1].to_dict()
    assert body["choices"][0]["delta"]["tool_calls"][0]["index"] == 0

    assert chunks[2].choices[0].finish_reason == "tool_calls"
    assert chunks[3].choices == ()
    assert chunks[3].usage is not None
    assert chunks[3].screamingface is not None


def test_build_completion_equals_the_reply_of_the_lines() -> None:
    """MI-4: the reply built from the chunks equals the reply of the lines."""

    body = wire(WITH_TEXT_CALLS)
    assert build_completion(_chunks(body)) == _reply(body)


def test_lines_after_done_are_not_read() -> None:
    """MI-4 / C2.3: the lines after [DONE] are not read, so bad JSON there is harmless."""

    lines = lines_from_bytes(wire(TEXT)) + ["data: {not json"]
    result = completion_from_lines(lines)
    assert isinstance(result, ChatCompletion)
    assert result.text == "Hello"
