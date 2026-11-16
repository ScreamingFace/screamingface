"""The run's result spool, wired through the composition root (memory fix 3, OME-1835, wave 3).

WHY these tests: the spool is made, bound and closed once per run by OperationCapturingExecutor,
and the composition root hands it a factory over the run's result store. A store that cannot
stream (a test double) gets no factory, so its runs keep today's whole-string path. A failing
run still closes its spool, so no reference outlives its run.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.artifacts.spool import (
    ResultSpool,
    ResultSpoolClosed,
    bound_result_spool,
)
from screamingface_engine.runner.main import build_executor, result_spools
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import LogData


class _OnlyBytes:
    def write_bytes(self, data: bytes) -> object:
        raise AssertionError(data)

    def write_text(self, text: str) -> object:
        raise AssertionError(text)


class _SpoolProbe(Executor):
    """Records the spool bound at each of its two yields."""

    def __init__(self) -> None:
        self.seen: list[ResultSpool | None] = []

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        del url4, trace
        self.seen.append(bound_result_spool())
        yield LogData.at("INFO", "first")
        self.seen.append(bound_result_spool())
        yield LogData.at("INFO", "second")


class _FailingProbe(Executor):
    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        del url4, trace
        yield LogData.at("INFO", "first")
        raise RuntimeError("boom")


def test_result_spools_makes_a_spool_with_the_runs_caps(tmp_path: Path) -> None:
    factory = result_spools(FilesystemArtifactStore(tmp_path), inline_cap=7, hard_cap=9)

    assert factory is not None
    spool = factory()
    assert isinstance(spool, ResultSpool)
    assert (spool.inline_cap, spool.hard_cap) == (7, 9)


def test_a_store_that_cannot_stream_gets_no_spool() -> None:
    assert result_spools(_OnlyBytes(), inline_cap=1, hard_cap=2) is None  # type: ignore[arg-type]
    assert result_spools(None, inline_cap=1, hard_cap=2) is None


def test_build_executor_wires_a_spool_factory(tmp_path: Path) -> None:
    executor = build_executor({"URL4_CLOUD_TOPIC": "t", "URL4_CLOUD_ARTIFACTS_DIR": str(tmp_path)})

    assert executor._result_spools is not None


@pytest.mark.asyncio
async def test_each_run_binds_its_own_spool_and_closes_it() -> None:
    inner = _SpoolProbe()
    made: list[ResultSpool] = []

    def factory() -> ResultSpool:
        spool = ResultSpool(None, inline_cap=10, hard_cap=10)
        made.append(spool)
        return spool

    executor = OperationCapturingExecutor(inner, result_spools=factory)
    for _ in range(2):
        _ = [step async for step in executor.execute("'x'")]

    assert len(made) == 2
    assert inner.seen == [made[0], made[0], made[1], made[1]]
    assert made[0] is not made[1]
    assert bound_result_spool() is None
    for spool in made:
        with pytest.raises(ResultSpoolClosed):
            spool.deliver(lambda write: write("a"))


@pytest.mark.asyncio
async def test_a_failing_run_still_closes_its_spool() -> None:
    made: list[ResultSpool] = []

    def factory() -> ResultSpool:
        spool = ResultSpool(None, inline_cap=10, hard_cap=10)
        made.append(spool)
        return spool

    executor = OperationCapturingExecutor(_FailingProbe(), result_spools=factory)
    with pytest.raises(RuntimeError):
        _ = [step async for step in executor.execute("'x'")]

    assert len(made) == 1
    with pytest.raises(ResultSpoolClosed):
        made[0].deliver(lambda write: write("a"))
