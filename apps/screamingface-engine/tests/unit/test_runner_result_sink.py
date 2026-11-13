"""E5 P2 spec R5 and D9a: a driver-started run writes its result to the run-results store before it
publishes the result frame.

FEATURE: a detached Run (OME-1837). STORY: as a researcher, every result my detached Run produced
is still there when I come back, whatever its size.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.artifacts.ports import ArtifactContent
from screamingface_engine.artifacts.run_results import (
    RESULT_STORE_MISSING,
    RESULT_STORE_UNAVAILABLE,
    FilesystemRunResultStore,
    ResultSink,
    result_prefix,
)
from screamingface_engine.artifacts.wiring import result_sink_from_env
from screamingface_engine.runner.executor import Url4Executor, _RunState
from url4.core.errors import ResolutionError

PREFIX = result_prefix(f"run_{'a' * 32}", 0)


class _Refusing:
    """A run-results store that refuses every write, as an unreachable bucket does."""

    def __init__(self) -> None:
        self.puts = 0

    def put(self, key: str, body: bytes) -> None:
        self.puts += 1
        raise OSError("the bucket is unreachable")

    def open(self, key: str) -> ArtifactContent | None:
        return None

    def delete(self, keys: Iterable[str]) -> None:
        return None

    def delete_older_than(self, cutoff: datetime) -> int:
        return 0


def _stored(root: Path, body: str) -> bytes:
    digest = hashlib.sha256(body.encode()).hexdigest()
    return (root / PREFIX / digest).read_bytes()


def test_an_inline_result_is_written_before_its_frame_and_the_frame_is_unchanged(
    tmp_path: Path,
) -> None:
    sink = ResultSink(PREFIX, FilesystemRunResultStore(tmp_path))

    data = _RunState().build_result("ok", inline_cap=1024, hard_cap=4096, store=None, sink=sink)

    assert data.body == "ok"
    assert _stored(tmp_path, "ok") == b"ok"


def test_a_spilled_result_is_written_too_and_still_spills(tmp_path: Path) -> None:
    body = "x" * 2048
    sink = ResultSink(PREFIX, FilesystemRunResultStore(tmp_path / "results"))
    spill = FilesystemArtifactStore(tmp_path / "artifacts")

    data = _RunState().build_result(body, inline_cap=1024, hard_cap=4096, store=spill, sink=sink)

    assert data.artifact is not None
    assert _stored(tmp_path / "results", body) == body.encode()


def test_a_store_that_keeps_refusing_fails_the_run_not_permanently() -> None:
    store = _Refusing()
    sink = ResultSink(PREFIX, store, budget_s=0)

    with pytest.raises(ResolutionError) as raised:
        _RunState().build_result("ok", inline_cap=1024, hard_cap=4096, store=None, sink=sink)

    assert raised.value.code == RESULT_STORE_UNAVAILABLE
    assert raised.value.permanent is False
    assert store.puts == 1


def test_a_run_without_a_sink_writes_nothing(tmp_path: Path) -> None:
    """INVARIANT (plan E2): a start without a result prefix is today's artifact write."""
    data = _RunState().build_result("ok", inline_cap=1024, hard_cap=4096, store=None)

    assert data.body == "ok"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_a_prefix_with_no_store_fails_before_any_model_call() -> None:
    """R5: `result_store_missing`, before the world is even built."""
    built: list[bool] = []

    async def world_factory() -> Any:
        built.append(True)
        raise AssertionError("no world may be built")

    executor = Url4Executor(world_factory=world_factory, result_sink=ResultSink(PREFIX, None))
    steps: AsyncIterator[Any] = executor.execute("openai/gpt-5")

    with pytest.raises(ResolutionError) as raised:
        await anext(steps)

    assert raised.value.code == RESULT_STORE_MISSING
    assert built == []


def test_the_sink_comes_from_the_runs_env(tmp_path: Path) -> None:
    env = {
        job_env.RESULT_PREFIX: PREFIX,
        job_env.RUN_RESULTS_STORE: "filesystem",
        job_env.RUN_RESULTS_DIR: str(tmp_path),
        job_env.RUN_RESULT_WRITE_BUDGET_S: "12",
    }

    sink = result_sink_from_env(env)

    assert sink is not None
    assert (sink.prefix, sink.budget_s) == (PREFIX, 12.0)
    assert isinstance(sink.store, FilesystemRunResultStore)


def test_a_run_without_a_prefix_has_no_sink() -> None:
    assert result_sink_from_env({job_env.RUN_RESULTS_STORE: "filesystem"}) is None


def test_a_prefix_on_a_pool_with_no_store_has_a_sink_with_none() -> None:
    sink = result_sink_from_env({job_env.RESULT_PREFIX: PREFIX})

    assert sink is not None
    assert sink.store is None


# --- the store answers before any model call (review of #1747) ------------------------------


@pytest.mark.asyncio
async def test_a_store_that_does_not_answer_fails_the_run_before_any_model_call() -> None:
    """R5: a run that could not keep its result is found out before it spends, not after."""
    built: list[bool] = []

    async def world_factory() -> Any:
        built.append(True)
        raise AssertionError("no world may be built")

    store = _Refusing()
    executor = Url4Executor(
        world_factory=world_factory, result_sink=ResultSink(PREFIX, store, budget_s=0)
    )
    steps: AsyncIterator[Any] = executor.execute("openai/gpt-5")

    with pytest.raises(ResolutionError) as raised:
        await anext(steps)

    assert (raised.value.code, raised.value.permanent) == (RESULT_STORE_UNAVAILABLE, False)
    assert built == []
    assert store.puts == 1


@pytest.mark.asyncio
async def test_a_store_that_answers_is_written_once_before_the_world_is_built(
    tmp_path: Path,
) -> None:
    """The check is a write, since the runner pool's key may only write. Its object is the
    empty result's key under the Candidate's prefix, so it names nothing new."""
    order: list[str] = []
    store = FilesystemRunResultStore(tmp_path)

    async def world_factory() -> Any:
        order.append("world")
        raise RuntimeError("stop here")

    executor = Url4Executor(world_factory=world_factory, result_sink=ResultSink(PREFIX, store))
    steps: AsyncIterator[Any] = executor.execute("openai/gpt-5")

    with pytest.raises(Exception, match="stop here"):
        await anext(steps)

    assert _stored(tmp_path, "") == b""
    assert order == ["world"]
