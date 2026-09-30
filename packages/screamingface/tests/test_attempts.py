"""`drive_sync` and `drive_async` send, settle and send again (E14 simplify, `_core/attempts.py`).

The two drivers are twins, so every test runs against both. The settle rule is a plain function
here, so nothing needs a clock, a socket or a mock transport.
"""

from __future__ import annotations

import httpx
import pytest

from screamingface._core.attempts import _Again, _Attempt, _Done, _Step, drive_async, drive_sync

CATCH = (httpx.HTTPError,)


class _Script:
    """A scripted `send` and a recording `settle` and `sleep`, shared by both drivers."""

    def __init__(self, sends: list[httpx.Response | Exception], steps: list[_Step[str]]) -> None:
        self._sends = list(sends)
        self._steps = list(steps)
        self.settled: list[tuple[int, _Attempt]] = []
        self.sleeps: list[float] = []

    def next_send(self) -> httpx.Response:
        item = self._sends.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def settle(self, attempt: int, outcome: _Attempt) -> _Step[str]:
        self.settled.append((attempt, outcome))
        return self._steps.pop(0)

    def sync_sleep(self, delay: float) -> None:
        self.sleeps.append(delay)

    async def async_send(self) -> httpx.Response:
        return self.next_send()

    async def async_sleep(self, delay: float) -> None:
        self.sleeps.append(delay)


def _run_sync(script: _Script, catch: tuple[type[Exception], ...] = CATCH) -> str:
    return drive_sync(script.next_send, script.settle, script.sync_sleep, catch)


async def _run_async(script: _Script, catch: tuple[type[Exception], ...] = CATCH) -> str:
    return await drive_async(script.async_send, script.settle, script.async_sleep, catch)


OK = httpx.Response(200)


def test_a_done_step_returns_its_value_without_a_sleep() -> None:
    script = _Script([OK], [_Done("value")])

    assert _run_sync(script) == "value"
    assert script.settled == [(0, OK)]
    assert script.sleeps == []


def test_an_again_with_no_delay_sends_at_once_and_never_calls_sleep() -> None:
    script = _Script([OK, OK], [_Again(None), _Done("value")])

    assert _run_sync(script) == "value"
    assert len(script.settled) == 2
    assert script.sleeps == []


def test_an_again_with_a_delay_sleeps_that_long_before_the_next_send() -> None:
    script = _Script([OK, OK, OK], [_Again(0.5), _Again(1.0), _Done("value")])

    assert _run_sync(script) == "value"
    assert script.sleeps == [0.5, 1.0]


def test_the_attempt_index_counts_the_settled_attempts() -> None:
    script = _Script([OK, OK, OK], [_Again(None), _Again(None), _Done("value")])

    _run_sync(script)

    assert [attempt for attempt, _ in script.settled] == [0, 1, 2]


def test_a_caught_exception_becomes_the_outcome() -> None:
    error = httpx.ConnectError("down")
    script = _Script([error, OK], [_Again(None), _Done("value")])

    assert _run_sync(script) == "value"
    assert script.settled[0] == (0, error)
    assert script.settled[1] == (1, OK)


def test_an_exception_outside_the_catch_tuple_leaves_the_loop_and_is_never_settled() -> None:
    script = _Script([ValueError("boom")], [_Done("never")])

    with pytest.raises(ValueError, match="boom"):
        _run_sync(script)

    assert script.settled == []


def test_a_settle_that_raises_ends_the_loop_with_its_error() -> None:
    def settle(_attempt: int, _outcome: _Attempt) -> _Step[str]:
        raise RuntimeError("terminal")

    with pytest.raises(RuntimeError, match="terminal"):
        drive_sync(lambda: OK, settle, lambda _delay: None, CATCH)


@pytest.mark.asyncio
async def test_async_a_done_step_returns_its_value_without_a_sleep() -> None:
    script = _Script([OK], [_Done("value")])

    assert await _run_async(script) == "value"
    assert script.settled == [(0, OK)]
    assert script.sleeps == []


@pytest.mark.asyncio
async def test_async_an_again_with_no_delay_sends_at_once_and_never_calls_sleep() -> None:
    script = _Script([OK, OK], [_Again(None), _Done("value")])

    assert await _run_async(script) == "value"
    assert script.sleeps == []


@pytest.mark.asyncio
async def test_async_an_again_with_a_delay_sleeps_that_long_before_the_next_send() -> None:
    script = _Script([OK, OK, OK], [_Again(0.5), _Again(1.0), _Done("value")])

    assert await _run_async(script) == "value"
    assert script.sleeps == [0.5, 1.0]


@pytest.mark.asyncio
async def test_async_the_attempt_index_counts_the_settled_attempts() -> None:
    script = _Script([OK, OK, OK], [_Again(None), _Again(None), _Done("value")])

    await _run_async(script)

    assert [attempt for attempt, _ in script.settled] == [0, 1, 2]


@pytest.mark.asyncio
async def test_async_a_caught_exception_becomes_the_outcome() -> None:
    error = httpx.ReadTimeout("slow")
    script = _Script([error, OK], [_Again(None), _Done("value")])

    assert await _run_async(script) == "value"
    assert script.settled[0] == (0, error)


@pytest.mark.asyncio
async def test_async_an_exception_outside_the_catch_tuple_leaves_the_loop() -> None:
    script = _Script([ValueError("boom")], [_Done("never")])

    with pytest.raises(ValueError, match="boom"):
        await _run_async(script)

    assert script.settled == []
