"""Run-session lifetime is isolated even when async generators change consuming tasks."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from screamingface_engine.activity.contract import ActivityLevel
from screamingface_engine.activity.session import current_session
from screamingface_engine.observation_plugins import observation_factories
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import LogData


class Probe(Executor):
    def __init__(self):
        self.sessions = []

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        self.sessions.append(current_session())
        try:
            yield LogData.at("INFO", "probe")
        finally:
            self.sessions.append(current_session())


@pytest.mark.asyncio
async def test_full_session_rebinds_for_cross_task_close_then_revokes():
    probe = Probe()
    iterator = OperationCapturingExecutor(
        probe, observers=observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": "full"})
    ).execute("x")

    async def advance():
        return await anext(iterator)

    await asyncio.create_task(advance())
    assert current_session() is None
    await asyncio.create_task(getattr(iterator, "aclose")())
    first, final = probe.sessions
    assert first is not None and first is final
    assert not first.active
    assert current_session() is None


@pytest.mark.asyncio
async def test_full_runs_have_distinct_sessions_and_off_allocates_none():
    first, second, off = Probe(), Probe(), Probe()

    async def consume(probe, level):
        return [
            s
            async for s in OperationCapturingExecutor(
                probe, observers=observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": level})
            ).execute("x")
        ]

    await asyncio.gather(
        consume(first, ActivityLevel.FULL),
        consume(second, ActivityLevel.FULL),
        consume(off, ActivityLevel.OFF),
    )
    assert first.sessions[0] is not second.sessions[0]
    assert off.sessions == [None, None]


@pytest.mark.asyncio
async def test_nested_off_registration_masks_parent_activity_session():
    from screamingface_engine.activity.session import current_session
    from screamingface_engine.observation_plugins import observation_factories
    from screamingface_engine.observations import RunObservations

    outer = RunObservations(observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": "full"}))
    inner = RunObservations(observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": "off"}))
    with outer.bind():
        session = current_session()
        assert session is not None
        with inner.bind():
            assert current_session() is None
        assert current_session() is session
    await inner.aclose()
    await outer.aclose()


@pytest.mark.asyncio
async def test_run_cleanup_stops_abandoned_activity_heartbeat():
    import asyncio

    from screamingface_engine.observation_plugins import observation_factories
    from screamingface_engine.observations import ModelCall, RunObservations

    run = RunObservations(observation_factories({"URL4_CLOUD_ACTIVITY_LEVEL": "full"}))
    entered, release = asyncio.Event(), asyncio.Event()
    records = []

    def emit(body, attributes=None, *, severity="INFO"):
        records.append(attributes)

    async def child():
        async with ModelCall("model", emit):
            entered.set()
            await release.wait()

    with run.bind():
        task = asyncio.create_task(child())
        await entered.wait()
    await run.aclose()
    assert not [t for t in asyncio.all_tasks() if "Operation._heartbeat" in str(t.get_coro())]
    release.set()
    await task
    assert len(records) == 1  # no late terminal after revocation


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
