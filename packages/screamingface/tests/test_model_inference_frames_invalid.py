"""MI-5: a stream with a wrong form is a FrameError, and the error event is a typed value.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C2.3, C2.4,
C4.1).
INVARIANT: no transport; no SDK error class here (unit U4 maps them).
"""

from __future__ import annotations

from typing import Any

import pytest
from _chat_frames import (
    DONE_LINE,
    KEEP_ALIVE,
    META,
    SECOND_CALL,
    TOOL_CALL,
    USAGE,
    choice,
    chunk,
    data_line,
    engine_stream,
    error_line,
    info,
    wire,
)

from screamingface._inference.frames import (
    FrameError,
    StreamError,
    build_completion,
    completion_from_lines,
    lines_from_bytes,
    read_chunks,
)
from screamingface.errors import ScreamingFaceError

TEXT = engine_stream({"role": "assistant", "content": "Hi"}, "stop")
NO_RETRY = {"message": "failed", "type": "server_error", "code": "timeout", "should_retry": False}
RETRY = {
    "message": "restart",
    "type": "server_error",
    "code": "server_restarting",
    "should_retry": True,
    "retry_after": 5,
}
NO_FLAG = {"message": "failed", "type": "server_error", "code": "timeout"}
BAD = {"message": "m", "type": "t", "code": "c"}


def _tail(**changes: Any) -> dict[str, Any]:
    """The usage chunk, with the changed keys of its screamingface object."""

    return chunk([], usage=USAGE, screamingface=info(**changes))


def _tool_call_pieces() -> bytes:
    """A tool call that comes in two pieces, the second with no id (not joined, contracts C2.3)."""

    first = {**TOOL_CALL, "index": 0, "function": {"name": "get_weather", "arguments": '{"city":'}}
    second = {"index": 0, "function": {"arguments": '"Paris"}'}}
    return wire(
        [
            chunk([choice({"role": "assistant"})]),
            chunk([choice({"tool_calls": [first]})]),
            chunk([choice({"tool_calls": [second]})]),
        ]
    )


@pytest.mark.parametrize(
    ("name", "body", "reason"),
    [
        ("not-json", b'data: {"secret Paris"\n\n', "not_json"),
        ("not-utf8", b"data: \xff\xfe\n\n", "not_text"),
        ("json-array", wire([[1, 2]]), "wrong_shape"),
        ("no-done", wire(TEXT, done=False), "truncated"),
        ("keep-alive-only", KEEP_ALIVE + KEEP_ALIVE, "truncated"),
        ("empty-body", b"", "truncated"),
        ("only-done", DONE_LINE, "wrong_shape"),
        (
            "no-finish-reason",
            wire(
                [
                    chunk([choice({"role": "assistant", "content": "Hi"})]),
                    chunk([], usage=USAGE, screamingface=info()),
                ]
            ),
            "wrong_shape",
        ),
        (
            "no-usage-chunk",
            wire(
                [
                    chunk([choice({"role": "assistant", "content": "Hi"})]),
                    chunk([choice({}, "stop")], screamingface=info()),
                ]
            ),
            "wrong_shape",
        ),
        (
            "no-screamingface",
            wire(
                [
                    chunk([choice({"role": "assistant", "content": "Hi"})]),
                    chunk([choice({}, "stop")]),
                    chunk([], usage=USAGE),
                ]
            ),
            "wrong_shape",
        ),
        ("chunk-without-choices", wire([dict(META)]), "wrong_shape"),
        (
            "chunk-without-id",
            wire([{k: v for k, v in chunk([]).items() if k != "id"}]),
            "wrong_shape",
        ),
        ("created-is-text", wire([{**chunk([]), "created": "x"}]), "wrong_shape"),
        ("created-is-bool", wire([{**chunk([]), "created": True}]), "wrong_shape"),
        ("created-is-negative", wire([{**chunk([]), "created": -1}]), "wrong_shape"),
        ("choice-not-object", wire([chunk(["x"])]), "wrong_shape"),
        (
            "choice-without-delta",
            wire([chunk([{"index": 0, "finish_reason": None}])]),
            "wrong_shape",
        ),
        ("content-is-a-number", wire([chunk([choice({"content": 5})])]), "wrong_shape"),
        (
            "tool-calls-not-a-list",
            wire([chunk([choice({"tool_calls": dict(TOOL_CALL)})])]),
            "wrong_shape",
        ),
        ("tool-call-delta-with-no-id", _tool_call_pieces(), "wrong_shape"),
        ("usage-is-text", wire([chunk([], usage="x")]), "wrong_shape"),
        (
            "cost-not-a-number",
            wire([*TEXT[:-1], _tail(cost_usd="abc")]),
            "wrong_shape",
        ),
        ("cost-nan", wire([*TEXT[:-1], _tail(cost_usd="NaN")]), "wrong_shape"),
        ("cost-is-a-json-number", wire([*TEXT[:-1], _tail(cost_usd=0.5)]), "wrong_shape"),
        (
            "final-step-without-model",
            wire([*TEXT[:-1], _tail(final_step={"binding": "model_1"})]),
            "wrong_shape",
        ),
    ],
)
def test_malformed_or_cut_stream_is_invalid_response(name: str, body: bytes, reason: str) -> None:
    """MI-5 / C2.3: a stream with a wrong form raises FrameError, with no value of the stream."""

    with pytest.raises(FrameError) as caught:
        completion_from_lines(lines_from_bytes(body))
    assert caught.value.reason == reason
    assert "Paris" not in str(caught.value)
    assert not isinstance(caught.value, ScreamingFaceError)


@pytest.mark.parametrize(
    ("name", "error", "expected"),
    [
        (
            "retry",
            RETRY,
            StreamError(
                message="restart",
                type="server_error",
                code="server_restarting",
                should_retry=True,
                retry_after=5,
            ),
        ),
        (
            "no-retry",
            NO_RETRY,
            StreamError(
                message="failed",
                type="server_error",
                code="timeout",
                should_retry=False,
                retry_after=None,
            ),
        ),
        (
            "engine-with-no-flag",
            NO_FLAG,
            StreamError(
                message="failed",
                type="server_error",
                code="timeout",
                should_retry=None,
                retry_after=None,
            ),
        ),
        (
            "unknown-keys",
            {**NO_RETRY, "param": None, "extra": 1},
            StreamError(
                message="failed",
                type="server_error",
                code="timeout",
                should_retry=False,
                retry_after=None,
            ),
        ),
    ],
)
def test_error_event_is_a_typed_value(
    name: str, error: dict[str, Any], expected: StreamError
) -> None:
    """MI-5 / C4.1: the error event is a StreamError, and the stream ends with no [DONE]."""

    body = data_line({"error": error})
    assert completion_from_lines(lines_from_bytes(body)) == expected
    assert list(read_chunks(lines_from_bytes(body))) == [expected]


def test_error_event_ends_the_read() -> None:
    """MI-5 / C2.3: the lines after an error event are not read."""

    body = (
        KEEP_ALIVE
        + error_line(message="failed", type="server_error", code="timeout", should_retry=False)
        + b"data: {not json\n\n"
    )
    result = completion_from_lines(lines_from_bytes(body))
    assert isinstance(result, StreamError)
    assert result.code == "timeout"


@pytest.mark.parametrize(
    "error",
    [
        "x",
        {"message": "m", "type": "t"},
        {**BAD, "should_retry": "yes"},
        {**BAD, "should_retry": True, "retry_after": True},
        {**BAD, "should_retry": True, "retry_after": -1},
        {**BAD, "should_retry": True, "retry_after": "5"},
    ],
)
def test_wrong_error_event_is_wrong_shape(error: Any) -> None:
    """MI-5 / C4.1: an error event with a wrong value is a FrameError (wrong_shape)."""

    with pytest.raises(FrameError) as caught:
        completion_from_lines(lines_from_bytes(data_line({"error": error})))
    assert caught.value.reason == "wrong_shape"


def test_build_completion_of_no_chunk_is_wrong_shape() -> None:
    """MI-5: a reply built from no chunk is a FrameError (wrong_shape)."""

    with pytest.raises(FrameError) as caught:
        build_completion([])
    assert caught.value.reason == "wrong_shape"


def _split(key: str) -> bytes:
    """A reply whose text (or refusal) comes in two deltas; the reader does not join pieces."""

    return wire(
        [
            chunk([choice({"role": "assistant", key: "Par"})]),
            chunk([choice({key: "is"})]),
            chunk([choice({}, "stop")]),
            chunk([], usage=USAGE, screamingface=info()),
        ]
    )


def _index_twice(*, same_chunk: bool) -> bytes:
    """Two tool calls with the same index 0, in one chunk or in two chunks."""

    first = {**TOOL_CALL, "index": 0}
    second = {**SECOND_CALL, "index": 0}
    calls = (
        [chunk([choice({"tool_calls": [first, second]})])]
        if same_chunk
        else [chunk([choice({"tool_calls": [first]})]), chunk([choice({"tool_calls": [second]})])]
    )
    return wire(
        [
            chunk([choice({"role": "assistant"})]),
            *calls,
            chunk([choice({}, "tool_calls")]),
            chunk([], usage=USAGE, screamingface=info()),
        ]
    )


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("content-in-two-deltas", _split("content")),
        ("refusal-in-two-deltas", _split("refusal")),
        ("tool-call-index-twice-in-one-chunk", _index_twice(same_chunk=True)),
        ("tool-call-index-twice-in-two-chunks", _index_twice(same_chunk=False)),
        ("cost-negative", wire([*TEXT[:-1], _tail(cost_usd="-0.0012")])),
    ],
)
def test_split_or_repeated_values_are_wrong_shape(name: str, body: bytes) -> None:
    """MI-5 / C2.3: the Engine sends the text once and each tool call once; a cost is not
    negative. Each other form is a FrameError (wrong_shape)."""

    with pytest.raises(FrameError) as caught:
        completion_from_lines(lines_from_bytes(body))
    assert caught.value.reason == "wrong_shape"
