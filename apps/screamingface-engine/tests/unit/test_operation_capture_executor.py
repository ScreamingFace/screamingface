"""Run-scoped operation capture at the ScreamingFace Engine composition boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from screamingface_engine.operation_calls import current_operation_calls
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import LogData


class _ProbeExecutor(Executor):
    def __init__(self, *, barrier: asyncio.Barrier | None = None) -> None:
        self.barrier = barrier
        self.recorder_ids: list[int] = []

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        del url4, trace
        recorder = current_operation_calls()
        assert recorder is not None
        self.recorder_ids.append(id(recorder))
        if self.barrier is not None:
            await self.barrier.wait()
        yield LogData.at("INFO", "started")


class _BlockingExecutor(Executor):
    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        del url4, trace
        self.entered.set()
        await asyncio.Event().wait()
        yield LogData.at("INFO", "unreachable")


@pytest.mark.asyncio
async def test_decorator_owns_one_scope_for_the_whole_inner_iteration() -> None:
    inner = _ProbeExecutor()
    executor = OperationCapturingExecutor(inner)

    assert current_operation_calls() is None
    assert len([step async for step in executor.execute("'hello'")]) == 1
    assert len(inner.recorder_ids) == 1
    assert current_operation_calls() is None


@pytest.mark.asyncio
async def test_concurrent_runs_never_share_their_operation_recorder() -> None:
    barrier = asyncio.Barrier(2)
    first = _ProbeExecutor(barrier=barrier)
    second = _ProbeExecutor(barrier=barrier)

    await asyncio.gather(
        _drain(OperationCapturingExecutor(first)),
        _drain(OperationCapturingExecutor(second)),
    )

    assert first.recorder_ids[0] != second.recorder_ids[0]


@pytest.mark.asyncio
async def test_nested_tasks_share_only_their_own_run_recorder() -> None:
    inner = _ProbeExecutor()

    async def recorder_id() -> int:
        recorder = current_operation_calls()
        assert recorder is not None
        return id(recorder)

    class _NestedExecutor(Executor):
        async def execute(
            self, url4: str, *, trace: TraceContext | None = None
        ) -> AsyncIterator[ExecStep]:
            del url4, trace
            parent = current_operation_calls()
            assert parent is not None
            child_ids = await asyncio.gather(recorder_id(), recorder_id())
            assert child_ids == [id(parent), id(parent)]
            async for step in inner.execute("nested"):
                yield step

    await _drain(OperationCapturingExecutor(_NestedExecutor()))


@pytest.mark.asyncio
async def test_early_iterator_close_unwinds_the_capture_scope() -> None:
    inner = _ProbeExecutor()
    iterator = OperationCapturingExecutor(inner).execute("'hello'")

    await anext(iterator)
    close = getattr(iterator, "aclose")
    await close()

    assert current_operation_calls() is None


@pytest.mark.asyncio
async def test_cancellation_unwinds_the_capture_scope_in_the_cancelled_task() -> None:
    inner = _BlockingExecutor()
    executor = OperationCapturingExecutor(inner)
    unwound = False

    async def consume() -> None:
        nonlocal unwound
        try:
            await anext(executor.execute("'hello'"))
        except asyncio.CancelledError:
            unwound = current_operation_calls() is None
            raise

    task = asyncio.create_task(consume())
    await inner.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert unwound is True


async def _drain(executor: Executor) -> None:
    async for _step in executor.execute("'hello'"):
        pass
