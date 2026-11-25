"""The push-form EventReader of the chat stream (contracts C2.3), unit U5."""

import pytest
from _chat_frames import DONE_LINE, KEEP_ALIVE, data_line, error_line, sse_lines

from screamingface._inference.frames import EventReader, FrameError, StreamError, events_from_lines


def test_event_reader_drops_keep_alive_and_blank_lines() -> None:
    reader = EventReader()

    assert reader.push(": keep-alive") is None
    assert reader.push("") is None
    assert reader.ended is False


def test_event_reader_gives_the_data_object_and_ends_at_done() -> None:
    reader = EventReader()

    assert reader.push('data: {"id":"x"}') == {"id": "x"}
    assert reader.ended is False
    assert reader.push("data: [DONE]") is None
    assert reader.ended is True
    reader.end()


def test_event_reader_ends_at_the_error_event() -> None:
    lines = sse_lines(
        error_line(message="m", type="server_error", code="timeout", should_retry=False)
    )
    reader = EventReader()

    events = [reader.push(line) for line in lines]
    error = next(e for e in events if e is not None)

    assert isinstance(error, StreamError)
    assert error.code == "timeout"
    assert reader.ended is True
    reader.end()


def test_event_reader_end_without_done_is_truncated() -> None:
    reader = EventReader()
    reader.push('data: {"a":1}')

    with pytest.raises(FrameError) as info:
        reader.end()

    assert info.value.reason == "truncated"


def test_event_reader_refuses_a_line_that_is_not_json() -> None:
    with pytest.raises(FrameError) as info:
        EventReader().push("data: {bad")

    assert info.value.reason == "not_json"


def test_events_from_lines_gives_the_same_events_as_the_reader() -> None:
    body = (
        KEEP_ALIVE
        + data_line({"id": "a"})
        + KEEP_ALIVE
        + data_line({"id": "b"})
        + DONE_LINE
        + data_line({"id": "after"})
    )
    lines = sse_lines(body)
    reader = EventReader()
    pushed: list[object] = []
    for line in lines:
        event = reader.push(line)
        if event is not None:
            pushed.append(event)
        if reader.ended:
            break

    assert list(events_from_lines(lines)) == pushed == [{"id": "a"}, {"id": "b"}]
