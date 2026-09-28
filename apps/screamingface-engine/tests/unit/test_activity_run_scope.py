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
