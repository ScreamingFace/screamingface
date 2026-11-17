"""An engine run refuses every url4:// remote-node call (OME-1811, #1450 spec F1b / §4, C6).

FEATURE: file inputs for url4 (epic OME-1529). Probe "Gap B" (2026-11-02): `Url4Executor`
called `url4.dag.run` directly, outside `Url4Node.evaluate`, so no refusal policy applied and a
remote call reached the world node's outbound layer. An empty peer allowlist stopped it with the
wrong code (`x.source_destination_blocked`); a populated one let it reach the peer.
STORY: as a node operator, nothing a run's expression says can make the engine call another node.

INVARIANT: a remote call, an ensemble member and a `url4://` reduce processor each fail
`x.remote_node_unsupported`, permanent, with zero outbound calls and zero DNS lookups, under both an
empty and a populated allowlist, on both `url4_run` call sites (with and without a trace). A local
run is unchanged.
"""

from __future__ import annotations

import pytest

from screamingface_engine.runner.executor import Url4Executor
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer, SourceGuard
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.peer.server import Url4Node
from url4.streaming.interfaces import Completed, TraceContext

PEERS = {"empty": frozenset(), "populated": frozenset({"n1", "n2.example", "n3.example"})}
TRACES = {"no-trace": None, "trace": TraceContext(trace_id="d" * 32, root_span_id="4" * 16)}
REDUCE = "(/a(x)!'i', /b(y)!'j')!'r'"
CASES = {
    "remote-call": ("url4://n2.example/v1(a)!'i'", None),
    "ensemble-member": ("(url4://n2.example/v1(a)!'i', url4://n3.example/v1(b)!'j')!'r'", None),
    "url4-reduce-processor": (REDUCE, "url4://n2.example/v1"),
}


class _Recorder:
    """Every call into the world node's outbound layer, and every DNS lookup under it.

    WHY a failing resolver and no socket mock: the guarded transport resolves a hostname before
    any connection, so a resolver that records and fails closed means no request can ever leave
    the test, and a recorded lookup is the observable for "the call got as far as DNS".
    """

    def __init__(self) -> None:
        self.dns: list[str] = []
        self.outbound: list[str] = []

    async def resolver(self, host: str, port: int) -> list[str]:
        self.dns.append(host)
        raise OSError("no DNS in this test")


class _Outbound:
    """The world node's outbound io, recording every call before delegating to the real one."""

    def __init__(self, rec: _Recorder, inner: HttpIOLayer) -> None:
        self._rec, self._inner = rec, inner

    async def fetch(self, target: str, *, relative: bool) -> str:
        self._rec.outbound.append(f"fetch {target}")
        return await self._inner.fetch(target, relative=relative)

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self._rec.outbound.append(f"fetch_ex {request.target}")
        return await self._inner.fetch_ex(request)

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self._rec.outbound.append(f"fetch_bytes {request.target}")
        return await self._inner.fetch_bytes(request)


@pytest.fixture
def rec() -> _Recorder:
    return _Recorder()


def _world(rec: _Recorder, peers: str, default_processor: str | None) -> Url4Node:
    io = HttpIOLayer(guard=SourceGuard(peer_hosts=PEERS[peers]), resolver=rec.resolver)
    node = Url4Node("n1", outbound=_Outbound(rec, io), default_processor=default_processor)
    node.endpoint("/a")(lambda r: "A")
    node.endpoint("/b")(lambda r: "B")
    return node


async def _execute(world: Url4Node, expression: str, trace: TraceContext | None) -> list:
    return [step async for step in Url4Executor(world).execute(expression, trace=trace)]


@pytest.mark.asyncio
@pytest.mark.parametrize("trace", sorted(TRACES))
@pytest.mark.parametrize("peers", sorted(PEERS))
@pytest.mark.parametrize("case", sorted(CASES))
async def test_an_engine_run_refuses_a_remote_node_call_before_any_io(
    rec: _Recorder, case: str, peers: str, trace: str
) -> None:
    expression, processor = CASES[case]
    with pytest.raises(ResolutionError) as caught:
        await _execute(_world(rec, peers, processor), expression, TRACES[trace])
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert rec.outbound == []
    assert rec.dns == []


@pytest.mark.asyncio
@pytest.mark.parametrize("trace", sorted(TRACES))
async def test_a_local_engine_run_is_unchanged(rec: _Recorder, trace: str) -> None:
    steps = await _execute(_world(rec, "populated", None), REDUCE, TRACES[trace])
    assert isinstance(steps[-1], Completed)
    assert rec.outbound == []
    assert rec.dns == []
