"""Releasing finished node results is opt-in; the default Executor caches across roots.

# FEATURE: url4 DAG execution memory (OME-1792, PR #1622 review, owner decision 2026-11-02:
#   opt-in release; the default keeps cross-root caching).
# INVARIANT: a default ``Executor`` reused for different roots resolves a shared node once.
# INVARIANT: a releasing ``Executor`` is single-root — a different root is refused with
#   ``ExecutorReuseError`` before any node is scheduled, never an AssertionError mid-run.
"""

from __future__ import annotations

import gc
import weakref
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from conftest import RecordingIOLayer

import url4.dag._run as run_module
from url4.dag import ExecutionContext, Payload, run
from url4.dag.executor import Executor, ExecutorReuseError
from url4.dag.node import DagNode


class _Big(list):
    """A list payload that can be weak-referenced (``str``/``list`` cannot)."""


class _Node:
    def __init__(
        self,
        name: str,
        fn: Callable[[Mapping[str, Any]], Payload],
        deps: dict[str, DagNode] | None = None,
    ) -> None:
        self.name = name
        self.resolves = 0
        self._fn = fn
        self._deps = deps or {}

    @property
    def deps(self) -> Mapping[str, DagNode]:
        return self._deps

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        self.resolves += 1
        return self._fn(inputs)


def _ctx() -> ExecutionContext:
    return ExecutionContext(RecordingIOLayer())


def _big_graph(refs: list[weakref.ref]) -> _Node:
    def make_big(_inputs: Mapping[str, Payload]) -> _Big:
        big = _Big(["x" * 1000])
        refs.append(weakref.ref(big))
        return big

    big = _Node("big", make_big)
    return _Node("root", lambda i: str(len(i["in"][0])), {"in": big})


@pytest.mark.asyncio
async def test_default_executor_resolves_a_leaf_shared_by_two_roots_once() -> None:
    # Dmitry's probe (PR #1622 review): it raised "nodes resolved != once" on the PR head.
    leaf = _Node("leaf", lambda _i: "l")
    first = _Node("first", lambda i: i["in"] + "1", {"in": leaf})
    second = _Node("second", lambda i: i["in"] + "2", {"in": leaf})
    ex = Executor(_ctx())

    assert await ex.execute(first) == "l1"
    assert await ex.execute(second) == "l2"
    assert (leaf.resolves, first.resolves, second.resolves) == (1, 1, 1)


@pytest.mark.asyncio
async def test_default_executor_keeps_finished_results() -> None:
    refs: list[weakref.ref] = []
    ex = Executor(_ctx())

    assert await ex.execute(_big_graph(refs)) == "1000"
    gc.collect()
    assert refs[0]() is not None  # cached for a later root, as before #1622


@pytest.mark.asyncio
async def test_releasing_executor_drops_a_finished_result() -> None:
    refs: list[weakref.ref] = []
    ex = Executor(_ctx(), release_finished=True)

    assert await ex.execute(_big_graph(refs)) == "1000"
    gc.collect()
    assert refs[0]() is None


@pytest.mark.asyncio
async def test_releasing_executor_still_answers_its_own_root() -> None:
    leaf = _Node("leaf", lambda _i: "l")
    root = _Node("root", lambda i: i["in"] + "!", {"in": leaf})
    ex = Executor(_ctx(), release_finished=True)

    assert await ex.execute(root) == "l!"
    assert await ex.execute(root) == "l!"
    assert (leaf.resolves, root.resolves) == (1, 1)


@pytest.mark.asyncio
async def test_releasing_executor_refuses_a_second_root_before_any_work() -> None:
    leaf = _Node("leaf", lambda _i: "l")
    first = _Node("first", lambda i: i["in"] + "1", {"in": leaf})
    second = _Node("second", lambda i: i["in"] + "2", {"in": leaf})
    ex = Executor(_ctx(), release_finished=True)

    assert await ex.execute(first) == "l1"
    with pytest.raises(ExecutorReuseError, match="single-root"):
        await ex.execute(second)
    with pytest.raises(ExecutorReuseError):
        await ex.execute_payload(second, _prevalidated=True)
    assert (leaf.resolves, second.resolves) == (1, 0)


@pytest.mark.asyncio
async def test_run_builds_a_releasing_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    # The engine run path (Url4Executor -> url4.dag.run) gets #1622's saving through here.
    built: list[bool] = []

    class _Spy(Executor):
        def __init__(self, ctx: ExecutionContext, *, release_finished: bool = False) -> None:
            built.append(release_finished)
            super().__init__(ctx, release_finished=release_finished)

    monkeypatch.setattr(run_module, "Executor", _Spy)
    leaf = _Node("leaf", lambda _i: "l")

    assert await run(_Node("root", lambda i: i["in"], {"in": leaf}), RecordingIOLayer()) == "l"
    assert built == [True]
