"""Direct observer cleanup and disabled-mode contracts, without deployment registration."""

import asyncio

import pytest

from screamingface_engine.activity.session import current_session


class HeldHeartbeats:
    def __init__(self):
        self.sleeping = asyncio.Event()
        self.cancelling = asyncio.Event()
        self.release = asyncio.Event()
        self.timers = set()
        self.stopped = set()

    async def sleep(self, _seconds):
        task = asyncio.current_task()
        self.timers.add(task)
        if len(self.timers) == 3:
            self.sleeping.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.stopped.add(task)
            self.cancelling.set()
            await self.release.wait()


async def assert_interrupted_cleanup(observer, held, cleanup, interruptions):
    await held.cancelling.wait()
    for _ in range(interruptions):
        cleanup.cancel()
        await asyncio.sleep(0)
    assert held.stopped == held.timers  # all cancelled before the first join
    assert not cleanup.done()  # cancellation cannot escape before timer finalizers finish
    held.release.set()
    with pytest.raises(asyncio.CancelledError):
        await cleanup
    assert all(task.done() for task in held.timers)
    assert not observer._calls


@pytest.mark.asyncio
@pytest.mark.parametrize("interruptions", [1, 2])
async def test_interrupted_cleanup_joins_every_abandoned_timer(monkeypatch, interruptions):
    from screamingface_engine.activity import scope
    from screamingface_engine.activity.observer import ActivityObserver

    held = HeldHeartbeats()
    monkeypatch.setattr(scope, "_sleep", held.sleep)
    observer = ActivityObserver()
    calls = []
    with observer.bind():
        for _ in range(3):
            call = observer.model_call("model", lambda *args, **kwargs: None)
            await call.start()
            calls.append(call)
        await held.sleeping.wait()
        cleanup = asyncio.create_task(observer.aclose())
        try:
            await assert_interrupted_cleanup(observer, held, cleanup, interruptions)
        finally:
            held.release.set()
            for task in held.timers:
                task.cancel()
            await asyncio.gather(cleanup, *held.timers, return_exceptions=True)
            for call in reversed(calls):
                await call.close(None, None, None)


@pytest.mark.asyncio
async def test_off_calls_are_inert_without_activity_allocation_or_tracking(monkeypatch):
    from screamingface_engine.activity import observer as activity
    from screamingface_engine.activity.scope import current_operation

    def forbidden(*args, **kwargs):
        raise AssertionError("off mode allocated an activity operation")

    monkeypatch.setattr(activity, "operation", forbidden)
    outer = activity.ActivityObserver()
    off = activity.ActivityObserver(enabled=False)
    with outer.bind():
        parent = current_session()
        with off.bind():
            assert current_session() is None
            first = off.model_call("a", None)
            assert off.model_call("b", None) is first
            await first.start()
            first.retry(attempt=2, delay_seconds=1)
            first.completed("stop")
            first.failed("timeout")
            await first.close(None, None, None)
            assert not off._calls
            assert current_operation() is None
        assert current_session() is parent
        await assert_off_model_dispatch(off)
    await outer.aclose()


async def assert_off_model_dispatch(off):
    from screamingface_engine.observations import ModelCall, RunObservations

    run = RunObservations((lambda: off,))
    with run.bind():
        async with ModelCall("a", None):
            assert current_session() is None
    await run.aclose()
