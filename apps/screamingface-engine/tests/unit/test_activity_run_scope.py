"""Run-session lifetime is isolated even when async generators change consuming tasks."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from screamingface_engine.activity.contract import ActivityLevel
from screamingface_engine.activity.session import current_session
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
    iterator = OperationCapturingExecutor(probe, activity_level=ActivityLevel.FULL).execute("x")

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
            s async for s in OperationCapturingExecutor(probe, activity_level=level).execute("x")
        ]

    await asyncio.gather(
        consume(first, ActivityLevel.FULL),
        consume(second, ActivityLevel.FULL),
        consume(off, ActivityLevel.OFF),
    )
    assert first.sessions[0] is not second.sessions[0]
    assert off.sessions == [None, None]
