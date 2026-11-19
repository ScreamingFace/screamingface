"""A refused remote node fails the run before ANY dependency runs (OME-1811 review, #1750).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run whose expression names another node fails before my node does
any work for it, so a local sibling (in the engine, a paid model call) never runs first.

INVARIANT: under :func:`url4.dag.refuse_remote_nodes`, a statically known ``url4://`` remote
expression anywhere in the graph, and a literal ``url4://`` reduce processor, fail
``x.remote_node_unsupported`` (permanent) with zero endpoint invocations, zero DNS lookups and
zero requests. The tripwire endpoints record every invocation; the local control proves they fire.
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

PEERS = {"empty": frozenset(), "populated": frozenset({"n1", "n2.example"})}
REDUCE = "(/a(x)!'i', /b(y)!'j')!'r'"
CASES = {
    "remote-member-beside-a-local-one": ("(url4://n2.example/v1(a)!'i', /a(x)!'j')!'r'", None),
    "local-member-listed-first": ("(/a(x)!'i', url4://n2.example/v1(a)!'j')!'r'", None),
    "remote-in-a-nested-group": (
        "(/a(x)!'i', (/b(y)!'k', url4://n2.example/v1(a)!'m')!'n')!'r'",
        None,
    ),
    "url4-reduce-processor": (REDUCE, "url4://n2.example/v1"),
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
        return httpx.Response(200, text="PEER-REACHED")


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Tripwire:
    tripwire = _Tripwire()
    monkeypatch.setattr(gt, "_inner_transport", lambda: httpx.MockTransport(tripwire.handler))
    return tripwire


def _world(wire: _Tripwire, peers: str, default_processor: str | None) -> Url4Node:
    io = HttpIOLayer(guard=SourceGuard(peer_hosts=PEERS[peers]), resolver=wire.resolver)
    node = Url4Node("n1", outbound=io, default_processor=default_processor)

    def endpoint(name: str):
        def handle(request: object) -> str:
            wire.calls.append(name)  # the tripwire: a local source that ran
            return name.upper()

        return handle

    node.endpoint("/a")(endpoint("a"))
    node.endpoint("/b")(endpoint("b"))
    return node


@pytest.mark.asyncio
@pytest.mark.parametrize("peers", sorted(PEERS))
@pytest.mark.parametrize("case", sorted(CASES))
async def test_a_refused_remote_node_fails_before_any_local_source_runs(
    wire: _Tripwire, case: str, peers: str
) -> None:
    expression, processor = CASES[case]
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(expression, _world(wire, peers, processor)))
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert wire.calls == []
    assert wire.dns == []
    assert wire.requests == []


@pytest.mark.asyncio
async def test_the_tripwire_fires_on_a_local_run(wire: _Tripwire) -> None:
    # WHY: proves the tripwire observes local sources, so the empty list above means "never ran".
    await refuse_remote_nodes(run(REDUCE, _world(wire, "populated", None)))
    assert sorted(wire.calls) == ["a", "a", "b"]  # both members, then the reduce on route /a
