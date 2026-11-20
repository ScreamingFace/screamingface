"""The settle step that the plain and the streamed answer share (review F3)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

import pytest
from _chat_app import TRACE_ID, chat_result, result_frame, terminated_frame

from screamingface_engine.rest import chat_wait
from screamingface_engine.rest.chat_errors import ChatError
from screamingface_engine.rest.chat_frames import RunFrames, WaitEnd
from screamingface_engine.rest.chat_observe import RequestFacts
from screamingface_engine.rest.chat_wait import WAIT_ROWS, settle_wait


@dataclass
class _Cleanup:
    finished: bool = False


@pytest.mark.parametrize("end", list(WAIT_ROWS))
def test_settle_wait_raises_the_wait_row_of_a_wait_end(end: WaitEnd) -> None:
    cleanup = _Cleanup()
    facts = RequestFacts(trace_id="before")
    with pytest.raises(ChatError) as caught:
        settle_wait(end, cast(Any, cleanup), facts)
    assert (caught.value.status, caught.value.code, caught.value.should_retry) == WAIT_ROWS[end]
    assert cleanup.finished is False
    assert facts.trace_id == "before"


def test_settle_wait_marks_a_terminal_run_finished_and_records_its_trace_id() -> None:
    frames = RunFrames(
        terminated=terminated_frame("t1"), result=result_frame("t1", chat_result()), root_cost=None
    )
    cleanup = _Cleanup()
    facts = RequestFacts(trace_id="before")
    assert settle_wait(frames, cast(Any, cleanup), facts) is frames
    assert cleanup.finished is True
    assert facts.trace_id == TRACE_ID


def test_settle_wait_keeps_the_request_trace_id_when_the_terminal_frame_has_none() -> None:
    frames = RunFrames(
        terminated=terminated_frame("t1", traceparent=None),
        result=result_frame("t1", chat_result()),
        root_cost=None,
    )
    cleanup = _Cleanup()
    facts = RequestFacts(trace_id="before")
    assert settle_wait(frames, cast(Any, cleanup), facts) is frames
    assert cleanup.finished is True
    assert facts.trace_id == "before"


@pytest.mark.asyncio
async def test_scan_outcome_is_the_one_timeout_rule() -> None:
    loop = asyncio.get_running_loop()
    scan: asyncio.Future[RunFrames] = loop.create_future()
    scan.set_exception(TimeoutError())
    gone: asyncio.Future[None] = loop.create_future()
    gone.cancel()
    assert chat_wait._scan_outcome(scan) is WaitEnd.TIMEOUT
    assert chat_wait._outcome(scan, gone) is WaitEnd.TIMEOUT
