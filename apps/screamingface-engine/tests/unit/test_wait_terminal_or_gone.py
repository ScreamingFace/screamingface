"""`wait_terminal_or_gone` ends in bounded time on each exit (PRD 02 §4).

FEATURE: the sync `GET /?q=` and the mount calls hold the request until the terminal frame of the
run, the bound, or the disconnect of the caller.

WHY these tests: the helper cancels its disconnect poll and then waits for the poll to end.
Starlette's `Request.is_disconnected` opens an `anyio.CancelScope` that is already cancelled. A
cancel of the poll task that arrives in that scope is swallowed when the scope exits, so the poll
continued and the helper did not return. Each test here limits its own wait, so a helper that
hangs fails the test and does not stop the suite.
"""

import asyncio
import contextlib
import gc
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from starlette.requests import Request

from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.rest import caller_watch
from screamingface_engine.rest.routes import WAIT_GONE, wait_terminal_or_gone
from url4.streaming.protocol import (
    ResultData,
    ResultEvent,
    TerminatedData,
    TerminatedEvent,
)

pytestmark = pytest.mark.asyncio

TOPIC = "wait-helper"
BOUND_S = 30.0
"""The bound of the wait in these tests: much longer than a test, so it is never the exit."""
LIMIT_S = 2.0
"""How long a test waits for the helper to end. The helper needs much less than this."""
ALIGNMENTS = range(8)
"""Event-loop turns between the start of the helper and the exit. The swallow needs the cancel
to arrive in the one turn where the poll is in the cancel scope, so the tests try each turn."""


def _terminated() -> TerminatedEvent:
    return TerminatedEvent(
        id=f"term-{TOPIC}",
        source=f"/trace/{TOPIC}/node/root",
        subject=TOPIC,
        data=TerminatedData(status="succeeded"),
    )


def _result() -> ResultEvent:
    return ResultEvent(
        id=f"res-{TOPIC}",
        source=f"/trace/{TOPIC}/node/root",
        subject=TOPIC,
        data=ResultData(body="42", media_type="application/json"),
    )


def _is_terminal(outcome: Any) -> bool:
    if outcome is None or outcome is WAIT_GONE:
        return False
    terminated, _ = outcome
    return isinstance(terminated, TerminatedEvent) and terminated.id == f"term-{TOPIC}"


class _SwallowsOneCancel:
    """A disconnect check that swallows its first cancel and then answers "connected".

    WHY: this is what Starlette's `Request.is_disconnected` can do, made deterministic.
    """

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.swallowed = 0

    async def __call__(self) -> bool:
        self.entered.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            if self.swallowed:
                raise
            self.swallowed += 1
        return False


class _SwallowsEachCancel:
    """A disconnect check that ignores each cancel and does not return until the test lets it."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancels = 0

    async def __call__(self) -> bool:
        self.entered.set()
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancels += 1
        return False


def _connected_request() -> Request:
    """A real Starlette request whose client stays connected for the full test."""

    async def receive() -> dict[str, Any]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable: the event is never set")

    scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []}
    return Request(scope, receive)


def _other_tasks() -> set[asyncio.Task[Any]]:
    """The tasks that are not done, without the test's own task."""
    return asyncio.all_tasks() - {asyncio.current_task()}


async def _ended(task: asyncio.Future[Any], within: float = LIMIT_S) -> bool:
    """True when `task` ended in time.

    INVARIANT: a task that did not end is cancelled until it ends, so a helper that hangs makes
    the test fail and never makes it hang.
    """
    in_time, _ = await asyncio.wait({task}, timeout=within)
    for _ in range(5):
        if task.done():
            break
        task.cancel()
        await asyncio.wait({task}, timeout=1.0)
    return bool(in_time)


async def _turns(count: int) -> None:
    for _ in range(count):
        await asyncio.sleep(0)


async def _tasks_left_after_some_turns() -> set[asyncio.Task[Any]]:
    """For a task that the helper abandoned or cancelled without a wait: it ends by itself."""
    for _ in range(20):
        if not _other_tasks():
            break
        await asyncio.sleep(0)
    return _other_tasks()


@contextlib.contextmanager
def _loop_reports() -> Iterator[list[dict[str, Any]]]:
    """What asyncio reports to the loop, for example "Task exception was never retrieved"."""
    loop = asyncio.get_running_loop()
    reported: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, context: reported.append(context))
    try:
        yield reported
        # asyncio reports an exception that nobody retrieved when the task object is collected.
        gc.collect()
    finally:
        loop.set_exception_handler(None)


@pytest.fixture
def one_reap_round_is_long(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make one round of the reap much longer than a test.

    WHY: the reap cancels the poll again after each round, and that also ends a poll that
    swallowed one cancel, one round late. With this fixture only the `released` check can end
    that poll in time. So these tests also pin that a swallowed cancel adds no delay.
    """
    monkeypatch.setattr(caller_watch, "_REAP_ROUND_S", 60.0)


# --- the defect, deterministic: a disconnect check that swallows one cancel -----------------


@pytest.mark.usefixtures("one_reap_round_is_long")
async def test_terminal_frame_ends_the_wait_when_the_check_swallows_one_cancel() -> None:
    stream = InMemoryEventStream()
    check = _SwallowsOneCancel()
    call = asyncio.ensure_future(wait_terminal_or_gone(stream, TOPIC, BOUND_S, check))
    await check.entered.wait()

    await stream.publish(TOPIC, _result())
    await stream.publish(TOPIC, _terminated())

    assert await _ended(call), "the helper did not return after the terminal frame"
    assert check.swallowed == 1  # the cancel was swallowed: the test did what it says
    outcome: Any = call.result()
    terminated, result = outcome
    assert terminated.id == f"term-{TOPIC}"
    assert result is not None and result.data.body == "42"
    # INVARIANT: no poll task stays alive after the helper returns.
    assert _other_tasks() == set()


@pytest.mark.usefixtures("one_reap_round_is_long")
async def test_caller_cancel_ends_the_wait_when_the_check_swallows_one_cancel() -> None:
    stream = InMemoryEventStream()
    check = _SwallowsOneCancel()
    call = asyncio.ensure_future(wait_terminal_or_gone(stream, TOPIC, BOUND_S, check))
    await check.entered.wait()

    call.cancel()

    assert await _ended(call), "the helper did not end after the cancel of its caller"
    assert check.swallowed == 1
    # INVARIANT: the helper passes the cancel of its caller on. It never swallows it.
    assert call.cancelled()
    assert _other_tasks() == set()


async def test_wait_is_bounded_when_the_check_ignores_each_cancel(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The helper must not depend on a well-behaved callable: it gives up after a bounded time."""
    monkeypatch.setattr(caller_watch, "_REAP_ROUND_S", 0.01)  # a fast test; the count is real
    stream = InMemoryEventStream()
    check = _SwallowsEachCancel()
    call = asyncio.ensure_future(wait_terminal_or_gone(stream, TOPIC, BOUND_S, check))
    await check.entered.wait()
    try:
        with caplog.at_level(logging.WARNING):
            await stream.publish(TOPIC, _terminated())
            ended = await asyncio.wait({call}, timeout=LIMIT_S)
        assert call in ended[0], "the helper did not return: its reap of the poll has no bound"
        assert _is_terminal(call.result())
        assert check.cancels == caller_watch._REAP_CANCELS > 1  # noqa: SLF001 - more than one try
        assert any("disconnect check" in record.getMessage() for record in caplog.records)
    finally:
        check.release.set()
        await _ended(call)
    # The check returned: the abandoned poll task sees that the wait is over, and it ends.
    assert await _tasks_left_after_some_turns() == set()


@pytest.mark.usefixtures("one_reap_round_is_long")
async def test_second_cancel_during_the_reap_ends_the_helper_at_once() -> None:
    """A caller that cancels again does not wait for the reap: both tasks have their cancel."""
    stream = InMemoryEventStream()
    check = _SwallowsEachCancel()
    call = asyncio.ensure_future(wait_terminal_or_gone(stream, TOPIC, BOUND_S, check))
    await check.entered.wait()
    try:
        call.cancel()
        await _turns(3)
        assert check.cancels == 1 and not call.done()  # the helper is in the reap now

        call.cancel()

        assert await _ended(call), "the helper did not end after the second cancel"
        assert call.cancelled()
    finally:
        check.release.set()
        await _ended(call)
    assert await _tasks_left_after_some_turns() == set()


# --- the defect, real: Starlette's `Request.is_disconnected` ---------------------------------


@pytest.mark.usefixtures("one_reap_round_is_long")
@pytest.mark.parametrize("turns", ALIGNMENTS)
async def test_terminal_frame_ends_the_wait_with_a_real_starlette_request(turns: int) -> None:
    """`turns == 0` is a run that ended before the wait started: the usual case in a fast test."""
    stream = InMemoryEventStream()

    async def publish_later() -> None:
        await _turns(turns)
        await stream.publish(TOPIC, _terminated())

    publisher: asyncio.Future[None] | None = None
    if turns == 0:
        await stream.publish(TOPIC, _terminated())
    else:
        publisher = asyncio.ensure_future(publish_later())
    call = asyncio.ensure_future(
        wait_terminal_or_gone(stream, TOPIC, BOUND_S, _connected_request().is_disconnected)
    )

    assert await _ended(call), "the helper did not return after the terminal frame"
    assert _is_terminal(call.result())
    if publisher is not None:
        await publisher
    assert _other_tasks() == set()


@pytest.mark.usefixtures("one_reap_round_is_long")
@pytest.mark.parametrize("turns", ALIGNMENTS)
async def test_caller_cancel_ends_the_wait_with_a_real_starlette_request(turns: int) -> None:
    stream = InMemoryEventStream()
    call = asyncio.ensure_future(
        wait_terminal_or_gone(stream, TOPIC, BOUND_S, _connected_request().is_disconnected)
    )
    await _turns(turns)

    call.cancel()

    assert await _ended(call), "the helper did not end after the cancel of its caller"
    assert call.cancelled()
    assert _other_tasks() == set()


# --- the contract of the helper, unchanged --------------------------------------------------


async def test_bound_passed_returns_none() -> None:
    stream = InMemoryEventStream()
    request = _connected_request()

    outcome = await asyncio.wait_for(
        wait_terminal_or_gone(stream, TOPIC, 0.05, request.is_disconnected), LIMIT_S
    )

    assert outcome is None
    assert _other_tasks() == set()


async def test_disconnect_returns_wait_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    # INVARIANT (PRD 02 §4): the hold is released within 1 s of a disconnect, so the time
    # between two checks must stay below 1 s. The poll is made fast only after this line.
    assert caller_watch.DISCONNECT_POLL_S < 1.0
    monkeypatch.setattr(caller_watch, "DISCONNECT_POLL_S", 0.01)
    stream = InMemoryEventStream()
    answers = [False, False, True]
    calls = 0

    async def is_disconnected() -> bool:
        nonlocal calls
        calls += 1
        return answers[calls - 1]

    outcome = await asyncio.wait_for(
        wait_terminal_or_gone(stream, TOPIC, BOUND_S, is_disconnected), LIMIT_S
    )

    assert outcome is WAIT_GONE
    assert calls == len(answers)  # the helper polled until the caller was gone
    assert _other_tasks() == set()


class _BrokenStream:
    def subscribe(self, topic: str, from_sequence: int | None = None) -> AsyncIterator[Any]:
        raise RuntimeError("stream broke")


async def test_failed_wait_raises_its_exception() -> None:
    stream: Any = _BrokenStream()
    request = _connected_request()

    with _loop_reports() as reported:
        with pytest.raises(RuntimeError, match="stream broke"):
            await asyncio.wait_for(
                wait_terminal_or_gone(stream, TOPIC, BOUND_S, request.is_disconnected), LIMIT_S
            )
        assert _other_tasks() == set()

    assert reported == []


async def test_failed_disconnect_check_leaves_no_unretrieved_exception() -> None:
    """A check that raises ends the wait as "gone" (the behaviour before this file). Its exception
    must be retrieved: asyncio must not report "Task exception was never retrieved"."""
    stream = InMemoryEventStream()

    async def is_disconnected() -> bool:
        raise RuntimeError("the receive channel broke")

    with _loop_reports() as reported:
        outcome = await asyncio.wait_for(
            wait_terminal_or_gone(stream, TOPIC, BOUND_S, is_disconnected), LIMIT_S
        )
        assert _other_tasks() == set()

    assert outcome is WAIT_GONE
    assert reported == []
