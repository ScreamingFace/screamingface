"""A remote node inside a Form-3 processor expression fails before any reduce member (OME-1811).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a reduce whose processor EXPRESSION itself calls another node
(``(url4://n2/v1(x)!'go')!'processor'``) is refused before my node runs a single reduce member,
even though the processor's final value is only known at run time.

INVARIANT: under :func:`url4.dag.refuse_remote_nodes`, every Form-3 processor graph is compiled
and walked for structural remote calls (a ``RemoteFetchNode``, a map body, a deferred group)
before any member runs, whether or not its value is statically computable. A local processor
graph still runs, and a processor whose fetched VALUE is ``url4://`` is still refused at run time.
"""

from __future__ import annotations

import httpx
import pytest

import url4.io._guarded_transport as gt
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import refuse_remote_nodes, run
from url4.io._source_policy import SourceGuard
from url4.io.http import HttpIOLayer
from url4.peer.server import Url4Node

REMOTE = "url4://n2.example/v1"
REDUCE = "(/a(x)!'i', /b(y)!'j')!'r'"
STRUCTURAL = {
    "remote-call-in-the-processor": f'({REMOTE}(x)!"go")!"processor"',
    "remote-call-beside-a-local-one": f"(/p(x)!'i', {REMOTE}(x)!'go')!'processor'",
    "remote-call-in-a-processor-map-body": f"(https://rows*({REMOTE}($item)!'i')!'per')!'p'",
    "remote-call-in-a-processor-nested-group": f"((/p(x)!'k', {REMOTE}(a)!'m')!'n')!'p'",
}


class _Tripwire:
    """Every endpoint invocation, DNS lookup and request this run causes."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.dns: list[str] = []
        self.requests: list[str] = []

    async def resolver(self, host: str, port: int) -> list[str]:
        self.dns.append(host)
        return ["93.184.216.34"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(f"{request.method} {request.url.host}{request.url.path}")
        rows = '["r1", "r2"]'
        return httpx.Response(200, text=rows, headers={"content-type": "application/json"})


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Tripwire:
    tripwire = _Tripwire()
    monkeypatch.setattr(gt, "_inner_transport", lambda: httpx.MockTransport(tripwire.handler))
    return tripwire


def _world(wire: _Tripwire, processor: str, p_reply: str = "/a") -> Url4Node:
    guard = SourceGuard(peer_hosts=frozenset({"n2.example", "rows"}))
    io = HttpIOLayer(guard=guard, resolver=wire.resolver)
    node = Url4Node("n1", outbound=io, default_processor=processor)

    def endpoint(name: str, reply: str):
        def handle(request: object) -> str:
            wire.calls.append(name)  # the tripwire: a local source that ran
            return reply

        return handle

    node.endpoint("/a")(endpoint("a", "A"))
    node.endpoint("/b")(endpoint("b", "B"))
    node.endpoint("/p")(endpoint("p", p_reply))
    return node


def _assert_refused(caught: pytest.ExceptionInfo[ResolutionError]) -> None:
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(STRUCTURAL))
async def test_a_remote_call_inside_a_processor_graph_fails_before_any_member(
    wire: _Tripwire, case: str
) -> None:
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(REDUCE, _world(wire, STRUCTURAL[case])))
    _assert_refused(caught)
    assert wire.calls == []
    assert wire.dns == []
    assert wire.requests == []


@pytest.mark.asyncio
async def test_a_local_processor_graph_still_runs(wire: _Tripwire) -> None:
    # Control: a processor graph with no remote call is computed at run time, as before.
    result = await refuse_remote_nodes(run(REDUCE, _world(wire, "(p:0:/p(x)!'i')!'$p'")))
    assert result == "A"  # the reduce dispatched to the computed route /a
    assert sorted(wire.calls) == ["a", "a", "b", "p"]


@pytest.mark.asyncio
async def test_a_processor_whose_fetched_value_is_remote_is_refused_at_run_time(
    wire: _Tripwire,
) -> None:
    # Control: the URI is a fetched value, unknowable before the run, so members run first.
    processor = "(p:0:/p(x)!'i')!'$p'"
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(REDUCE, _world(wire, processor, p_reply=REMOTE)))
    _assert_refused(caught)
    assert sorted(wire.calls) == ["a", "b", "p"]
    assert wire.requests == []
