"""An app-lifetime handler's close outlives a cancelled shutdown.

# FEATURE: Router Recipe extension Unit 5.1 (contract C7) — the attempt handler, like the usage
# accounting handler, is one app-lifetime LiteLLM client the shutdown closes.
# INVARIANT: the shutdown drops each handler before it closes it, so a close that a cancelled
# shutdown cut short would leave its connection pool open with no one left to close it. The
# close runs to its end, the later steps still run, and the cancellation is raised after them.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from aigateway.core.shutdown import close_through_cancellation

from .conftest import Harness

_FAILURE = "the handler did not close cleanly"
_LOG = logging.getLogger("shutdown-close-test")


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


class _SlowClose:
    """A handler whose close waits until the test lets it end."""

    def __init__(self, error: Exception | None = None) -> None:
        self.closing = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False
        self._error = error

    async def close(self) -> None:
        self.closing.set()
        await self.release.wait()
        if self._error is not None:
            raise self._error
        self.closed = True


# --- through the real app ---------------------------------------------------------------------


@pytest.mark.parametrize("builder", ["build_attempt_handler", "build_accounting_handler"])
def test_a_cancelled_shutdown_lets_the_handler_finish_closing(
    byom: Harness, monkeypatch: pytest.MonkeyPatch, builder: str
) -> None:
    from aigateway import main

    del byom
    monkeypatch.setenv("AIGW_TAXONOMY_ENABLED", "true")
    handler = _SlowClose()
    monkeypatch.setattr(main, builder, lambda: handler)
    app = main.create_app()
    later: list[str] = []
    real_close_db = main.close_db

    async def close_db() -> None:
        later.append("database")
        await real_close_db()

    monkeypatch.setattr(main, "close_db", close_db)

    async def cancel_while_closing() -> bool:
        async def run() -> None:
            async with app.router.lifespan_context(app):
                pass

        shutdown = asyncio.create_task(run())
        await handler.closing.wait()
        shutdown.cancel()
        await _settle()
        waited = not shutdown.done()
        handler.release.set()
        with pytest.raises(asyncio.CancelledError):
            await shutdown
        return waited

    waited = asyncio.run(cancel_while_closing())

    assert waited, "the cancelled shutdown did not wait for the close"
    assert handler.closed
    assert later == ["database"]


# --- the helper on its own --------------------------------------------------------------------


def test_a_failed_close_is_logged_and_never_raised(caplog: pytest.LogCaptureFixture) -> None:
    async def close() -> None:
        raise RuntimeError("pool refused to close")

    with caplog.at_level(logging.WARNING, logger=_LOG.name):
        asyncio.run(close_through_cancellation(close, _LOG, _FAILURE))

    assert [r.getMessage() for r in caplog.records if r.name == _LOG.name] == [_FAILURE]


def test_one_cancellation_waits_for_a_failing_close_then_is_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler = _SlowClose(error=RuntimeError("pool refused to close"))

    async def scenario() -> None:
        waiter = asyncio.create_task(close_through_cancellation(handler.close, _LOG, _FAILURE))
        await handler.closing.wait()
        waiter.cancel()
        await _settle()
        assert not waiter.done()
        handler.release.set()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    with caplog.at_level(logging.WARNING, logger=_LOG.name):
        asyncio.run(scenario())

    assert [r.getMessage() for r in caplog.records if r.name == _LOG.name] == [_FAILURE]


@pytest.mark.parametrize("error", [None, RuntimeError("pool refused to close")])
def test_every_cancellation_waits_for_the_close_then_is_raised(
    caplog: pytest.LogCaptureFixture, error: Exception | None
) -> None:
    # WHY: no later cancellation may cut the close short. A forced stop is not a cancellation of
    # this wait: it is the end of the loop itself (a second Ctrl+C, a killed process).
    handler = _SlowClose(error=error)

    async def scenario() -> None:
        waiter = asyncio.create_task(close_through_cancellation(handler.close, _LOG, _FAILURE))
        await handler.closing.wait()
        for _ in range(3):
            waiter.cancel()
            await _settle()
        assert not waiter.done()
        handler.release.set()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    with caplog.at_level(logging.WARNING, logger=_LOG.name):
        asyncio.run(scenario())

    logged = [r.getMessage() for r in caplog.records if r.name == _LOG.name]
    assert (handler.closed, logged) == ((True, []) if error is None else (False, [_FAILURE]))


def test_a_close_cancelled_twice_ends_before_the_loop_does() -> None:
    # WHY nothing releases the close here: `asyncio.run` cancels every task still pending when
    # its main coroutine returns, so a close the waiter stopped watching would be cut short.
    outcome = {"finished": False, "cancelled": False}

    async def close() -> None:
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            outcome["cancelled"] = True
            raise
        outcome["finished"] = True

    async def scenario() -> None:
        waiter = asyncio.create_task(close_through_cancellation(close, _LOG, _FAILURE))
        await _settle()
        waiter.cancel()
        await _settle()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    asyncio.run(scenario())

    assert outcome == {"finished": True, "cancelled": False}
