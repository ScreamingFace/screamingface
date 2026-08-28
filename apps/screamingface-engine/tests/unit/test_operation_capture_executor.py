"""Run-scoped operation capture at the ScreamingFace Engine composition boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from screamingface_engine.operation_calls import (
    current_request_accounting,
    operation_call_identity,
    record_operation_call,
)
from screamingface_engine.request_identity import model_request_key
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
        recorder = current_request_accounting()
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

    assert current_request_accounting() is None
    assert len([step async for step in executor.execute("'hello'")]) == 1
    assert len(inner.recorder_ids) == 1
    assert current_request_accounting() is None


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
        recorder = current_request_accounting()
        assert recorder is not None
        return id(recorder)

    class _NestedExecutor(Executor):
        async def execute(
            self, url4: str, *, trace: TraceContext | None = None
        ) -> AsyncIterator[ExecStep]:
            del url4, trace
            parent = current_request_accounting()
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

    assert current_request_accounting() is None


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
            unwound = current_request_accounting() is None
            raise

    task = asyncio.create_task(consume())
    await inner.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert unwound is True


@pytest.mark.asyncio
async def test_run_recorder_retains_request_accounting_without_model_output() -> None:
    captured = []

    class _AccountingExecutor(Executor):
        async def execute(
            self, url4: str, *, trace: TraceContext | None = None
        ) -> AsyncIterator[ExecStep]:
            del url4, trace
            with operation_call_identity(
                "/judge", {"seed": "1"}, context="private prompt", intent="grade"
            ):
                record_operation_call("private judge output", "stop")
            recorder = current_request_accounting()
            assert recorder is not None
            captured.extend(recorder)
            yield LogData.at("INFO", "started")

    await _drain(OperationCapturingExecutor(_AccountingExecutor()))

    assert len(captured) == 1
    assert captured[0].request_key == model_request_key(
        path="/judge", params={"seed": "1"}, context="private prompt", intent="grade"
    )
    assert not hasattr(captured[0], "output")


async def _drain(executor: Executor) -> None:
    async for _step in executor.execute("'hello'"):
        pass
