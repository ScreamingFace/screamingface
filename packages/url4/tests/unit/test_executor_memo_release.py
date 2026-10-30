"""Executor memo release: a node's result is dropped once its last consumer has it.

# FEATURE: url4 DAG execution memory — a 330 MB route result must not live for the whole run.
# INVARIANT: release never changes dedup — a shared node still resolves exactly once, every
#   consumer sees the same value, and the run's root stays memoised.
"""

from __future__ import annotations

import gc
import weakref
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from conftest import RecordingIOLayer

from url4.dag import ExecutionContext, Payload, run
from url4.dag.executor import Executor
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


def _probe(refs: list[weakref.ref], alive: list[bool]) -> Callable[[Mapping[str, Payload]], str]:
    def check(_inputs: Mapping[str, Payload]) -> str:
        gc.collect()
        alive.append(refs[0]() is not None)
        return "probed"

    return check


@pytest.mark.asyncio
async def test_result_is_dropped_after_its_only_consumer() -> None:
    refs: list[weakref.ref] = []
    alive: list[bool] = []

    def make_big(_inputs: Mapping[str, Payload]) -> _Big:
        big = _Big(["x" * 1000])
        refs.append(weakref.ref(big))
        return big

    big = _Node("big", make_big)
    consume = _Node("consume", lambda i: str(len(i["in"][0])), {"in": big})
    later = _Node("later", _probe(refs, alive), {"after": consume})
    sink = _Node("sink", lambda i: f"{i['c']}|{i['p']}", {"c": consume, "p": later})

    assert await run(sink, RecordingIOLayer()) == "1000|probed"
    assert alive == [False]


@pytest.mark.asyncio
async def test_shared_result_survives_until_every_consumer_has_it() -> None:
    refs: list[weakref.ref] = []
    seen: list[int] = []

    def make_big(_inputs: Mapping[str, Payload]) -> _Big:
        big = _Big(["v"])
        refs.append(weakref.ref(big))
        return big

    def read(inputs: Mapping[str, Any]) -> str:
        seen.append(id(inputs["in"]))
        return "".join(inputs["in"])

    big = _Node("big", make_big)
    left = _Node("left", read, {"in": big})
    right = _Node("right", read, {"in": big})
    # `twice` consumes `big` under two roles — two edges, one parent.
    twice = _Node("twice", lambda i: i["a"][0] + i["b"][0], {"a": big, "b": big})
    sink = _Node("sink", lambda i: f"{i['l']}{i['r']}{i['t']}", {"l": left, "r": right, "t": twice})

    assert await run(sink, RecordingIOLayer()) == "vvvv"
    assert big.resolves == 1
    assert len(set(seen)) == 1  # every consumer saw the one memoised value
    gc.collect()
    assert refs[0]() is None


@pytest.mark.asyncio
async def test_deep_diamond_still_resolves_each_node_once() -> None:
    base = _Node("base", lambda _i: "b")
    mids = [_Node(f"m{n}", lambda i: i["in"], {"in": base}) for n in range(5)]
    tops = [
        _Node(f"t{n}", lambda i: "".join(str(v) for v in i.values()), {"x": mids[n], "y": base})
        for n in range(5)
    ]
    sink = _Node(
        "sink",
        lambda i: ",".join(str(v) for v in i.values()),
        {f"t{n}": t for n, t in enumerate(tops)},
    )

    assert await run(sink, RecordingIOLayer()) == "bb,bb,bb,bb,bb"
    for node in (base, *mids, *tops, sink):
        assert node.resolves == 1, node.name


@pytest.mark.asyncio
async def test_reused_executor_keeps_the_root_memoised() -> None:
    leaf = _Node("leaf", lambda _i: "l")
    root = _Node("root", lambda i: i["in"] + "!", {"in": leaf})
    ex = Executor(ExecutionContext(RecordingIOLayer()))

    assert await ex.execute(root) == "l!"
    assert await ex.execute(root) == "l!"
    assert (leaf.resolves, root.resolves) == (1, 1)
