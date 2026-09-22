"""Executor memo invariant: a diamond dependency resolves exactly once.

Pins the invariant documented at :meth:`Executor._run
<url4.dag.executor.Executor._run>` — there is no ``await`` between the
``_memo`` check and the store, so a shared node schedules exactly one task.
The debug-mode guard added beside that comment asserts the invariant at the
end of every run; this test counts ``resolve`` calls independently, on a
hand-built diamond, with no mocking of the executor.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest
from conftest import RecordingIOLayer

from url4.dag import ExecutionContext, Payload, run
from url4.dag.node import DagNode


class _CountingNode:
    """A :class:`~url4.dag.node.DagNode` satisfying the protocol structurally.

    ``producer`` maps resolved inputs to this node's value; ``None`` makes the
    node a leaf that resolves to its own name. :attr:`resolves` counts every
    ``resolve`` call so the test can assert the memo collapsed the diamond.
    """

    def __init__(
        self,
        name: str,
        producer: Callable[[Mapping[str, Payload]], str] | None = None,
    ) -> None:
        self.name = name
        self.resolves = 0
        self._deps: dict[str, DagNode] = {}
        self._producer = producer

    @property
    def deps(self) -> Mapping[str, DagNode]:
        return self._deps

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> str:
        self.resolves += 1
        if self._producer is None:
            return self.name
        return self._producer(inputs)


@pytest.mark.asyncio
async def test_diamond_shared_node_resolves_exactly_once() -> None:
    # base is consumed by BOTH middle nodes, and both middle nodes feed the
    # sink — the diamond whose shared arm the memo must collapse to one task.
    base = _CountingNode("base")
    left = _CountingNode("left", lambda inputs: f"L({inputs['in']})")
    left._deps["in"] = base
    right = _CountingNode("right", lambda inputs: f"R({inputs['in']})")
    right._deps["in"] = base
    sink = _CountingNode("sink", lambda inputs: f"{inputs['l']}|{inputs['r']}")
    sink._deps.update({"l": left, "r": right})

    result = await run(sink, RecordingIOLayer())

    assert result == "L(base)|R(base)"
    for node in (base, left, right, sink):
        assert node.resolves == 1, f"{node.name} resolved {node.resolves} times"
