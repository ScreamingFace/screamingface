"""An engine run with a remote node in a map body or a computed processor fails (OME-1811, #1750).

FEATURE: file inputs for url4 (epic OME-1529); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run whose map body or Form-3 processor names another node is a
failed run that cost nothing: the collection is never fetched and no local source runs, and the
refusal is never folded into a `Completed` result as an `on_error=collect` error row.

INVARIANT: the map-body and static Form-3 processor cases raise `x.remote_node_unsupported`
(permanent) out of `Url4Executor.execute` with no `Completed` step, zero endpoint invocations and
zero DNS lookups (the collection host `rows` included). The tripwire endpoints record every
invocation; the local control proves they fire.
"""

from __future__ import annotations

import pytest

from screamingface_engine.runner.executor import Url4Executor
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer, SourceGuard
from url4.peer.server import Url4Node
from url4.streaming.interfaces import Completed, TraceContext

TRACES = {"no-trace": None, "trace": TraceContext(trace_id="e" * 32, root_span_id="5" * 16)}
REDUCE = "(/a(x)!'i', /b(y)!'j')!'r'"
CASES = {
    "map-body-collect": ('https://rows*(url4://n2.example/v1($item)!"i")!"per"', None),
    "static-form-3-processor": (REDUCE, "(p:0:'url4://n2.example/v1')!'$p'"),
}


class _Tripwire:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.dns: list[str] = []

    async def resolver(self, host: str, port: int) -> list[str]:
        self.dns.append(host)
        raise OSError("no DNS in this test")


@pytest.fixture
def wire() -> _Tripwire:
    return _Tripwire()


def _world(wire: _Tripwire, default_processor: str | None) -> Url4Node:
    guard = SourceGuard(peer_hosts=frozenset({"n2.example", "rows"}))
    io = HttpIOLayer(guard=guard, resolver=wire.resolver)
    node = Url4Node("n1", outbound=io, default_processor=default_processor)

    def endpoint(name: str):
        def handle(request: object) -> str:
            wire.calls.append(name)  # in the real engine this is a (paid) model source
            return name.upper()

        return handle

    node.endpoint("/a")(endpoint("a"))
    node.endpoint("/b")(endpoint("b"))
    return node


@pytest.mark.asyncio
@pytest.mark.parametrize("trace", sorted(TRACES))
@pytest.mark.parametrize("case", sorted(CASES))
async def test_an_engine_run_fails_rather_than_completing_with_an_error_row(
    wire: _Tripwire, case: str, trace: str
) -> None:
    expression, processor = CASES[case]
    steps: list[object] = []
    with pytest.raises(ResolutionError) as caught:
        async for step in Url4Executor(_world(wire, processor)).execute(
            expression, trace=TRACES[trace]
        ):
            steps.append(step)
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert not any(isinstance(step, Completed) for step in steps)
    assert wire.calls == []
    assert wire.dns == []


@pytest.mark.asyncio
async def test_the_engine_tripwire_fires_on_a_local_reduce(wire: _Tripwire) -> None:
    steps = [step async for step in Url4Executor(_world(wire, None)).execute(REDUCE)]
    assert isinstance(steps[-1], Completed)
    assert sorted(wire.calls) == ["a", "a", "b"]  # both members, then the reduce on route /a
