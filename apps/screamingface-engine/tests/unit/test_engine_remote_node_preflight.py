"""An engine run refuses a remote node before any local or model source runs (OME-1811, #1750).

FEATURE: file inputs for url4 (epic OME-1529); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run that names another node costs nothing: no local endpoint, and
so no paid gateway call, runs before the refusal.

INVARIANT: a remote member beside a local one, a remote call in a nested group, and a `url4://`
reduce processor each fail `x.remote_node_unsupported` (permanent) with zero endpoint
invocations, zero outbound calls and zero DNS lookups, on both `url4_run` call sites. The
tripwire endpoints record every invocation; the local control proves they fire.
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
    "remote-member-beside-a-local-one": ("(/a(x)!'i', url4://n2.example/v1(a)!'j')!'r'", None),
    "remote-in-a-nested-group": (
        "(/a(x)!'i', (/b(y)!'k', url4://n2.example/v1(a)!'m')!'n')!'r'",
        None,
    ),
    "url4-reduce-processor": (REDUCE, "url4://n2.example/v1"),
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
    guard = SourceGuard(peer_hosts=frozenset({"n2.example"}))
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


async def _execute(world: Url4Node, expression: str, trace: TraceContext | None) -> list:
    return [step async for step in Url4Executor(world).execute(expression, trace=trace)]


@pytest.mark.asyncio
@pytest.mark.parametrize("trace", sorted(TRACES))
@pytest.mark.parametrize("case", sorted(CASES))
async def test_an_engine_run_refuses_before_any_local_source_runs(
    wire: _Tripwire, case: str, trace: str
) -> None:
    expression, processor = CASES[case]
    with pytest.raises(ResolutionError) as caught:
        await _execute(_world(wire, processor), expression, TRACES[trace])
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert wire.calls == []
    assert wire.dns == []


@pytest.mark.asyncio
async def test_the_engine_tripwire_fires_on_a_local_run(wire: _Tripwire) -> None:
    steps = await _execute(_world(wire, None), REDUCE, None)
    assert isinstance(steps[-1], Completed)
    assert sorted(wire.calls) == ["a", "a", "b"]  # both members, then the reduce on route /a
