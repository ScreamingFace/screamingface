"""An engine run whose processor expression calls another node fails first (OME-1811, #1750).

FEATURE: file inputs for url4 (epic OME-1529); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a reduce whose Form-3 processor graph itself calls another node is a
failed run that cost nothing: no reduce member (in the engine, a paid model call) runs first.

INVARIANT: a remote call inside a processor graph raises `x.remote_node_unsupported` (permanent)
out of `Url4Executor.execute` with no `Completed` step, zero endpoint invocations and zero DNS
lookups. A local processor graph still runs; a processor whose fetched value is `url4://` is
still refused at run time. The tripwire endpoints record every invocation.
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
    "remote-call-in-the-processor": '(url4://n2.example/v1(x)!"go")!"processor"',
    "remote-call-in-a-processor-map-body": "(https://rows*(url4://n2.example/v1($item)!'i')!'p')!'q'",
}
LOCAL_PROCESSOR = "(p:0:/p(x)!'i')!'$p'"


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


def _world(wire: _Tripwire, default_processor: str | None, p_reply: str = "/a") -> Url4Node:
    guard = SourceGuard(peer_hosts=frozenset({"n2.example", "rows"}))
    io = HttpIOLayer(guard=guard, resolver=wire.resolver)
    node = Url4Node("n1", outbound=io, default_processor=default_processor)

    def endpoint(name: str):
        def handle(request: object) -> str:
            wire.calls.append(name)  # in the real engine this is a (paid) model source
            return p_reply if name == "p" else name.upper()

        return handle

    node.endpoint("/a")(endpoint("a"))
    node.endpoint("/b")(endpoint("b"))
    node.endpoint("/p")(endpoint("p"))
    return node


@pytest.mark.asyncio
@pytest.mark.parametrize("trace", sorted(TRACES))
@pytest.mark.parametrize("case", sorted(CASES))
async def test_an_engine_run_refuses_a_remote_processor_graph_before_any_member(
    wire: _Tripwire, case: str, trace: str
) -> None:
    steps: list[object] = []
    with pytest.raises(ResolutionError) as caught:
        async for step in Url4Executor(_world(wire, CASES[case])).execute(
            REDUCE, trace=TRACES[trace]
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
async def test_a_local_processor_graph_still_runs_in_the_engine(wire: _Tripwire) -> None:
    steps = [step async for step in Url4Executor(_world(wire, LOCAL_PROCESSOR)).execute(REDUCE)]
    assert isinstance(steps[-1], Completed)
    assert sorted(wire.calls) == ["a", "a", "b", "p"]  # members, processor graph, reduce on /a


@pytest.mark.asyncio
async def test_a_fetched_remote_processor_value_is_still_refused_in_the_engine(
    wire: _Tripwire,
) -> None:
    world = _world(wire, LOCAL_PROCESSOR, p_reply="url4://n2.example/v1")
    with pytest.raises(ResolutionError) as caught:
        _ = [step async for step in Url4Executor(world).execute(REDUCE)]
    assert caught.value.code == ErrorCode.REMOTE_NODE_UNSUPPORTED
    assert sorted(wire.calls) == ["a", "b", "p"]  # dynamic: only knowable at run time
    assert wire.dns == []
