"""The public ``url4.dag.refuse_remote_nodes`` hook refuses every remote-node call (``OME-1811``).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a host that runs ``url4.dag.run`` itself as a node (the engine), I wrap the run in the
supported hook so a ``url4://`` remote-node call fails ``x.remote_node_unsupported`` (permanent)
before any DNS lookup or request, exactly as ``Url4Node.evaluate`` does.

INVARIANT: the hook covers a remote expression, an ensemble member and a ``url4://`` reduce
processor, under BOTH an empty and a populated peer allowlist; without the hook a bare run still
reaches the peer (the gap this hook closes), and a local run is unchanged.
"""

from __future__ import annotations

import httpx
import pytest

import url4.dag
import url4.io._guarded_transport as gt
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import refuse_remote_nodes, run
from url4.io._source_policy import SourceGuard
from url4.io.http import HttpIOLayer
from url4.peer.server import Url4Node

PEERS = {"empty": frozenset(), "populated": frozenset({"n1", "n2.example", "n3.example"})}
REMOTE = "url4://n2.example/v1(a)!'i'"
ENSEMBLE = "(url4://n2.example/v1(a)!'i', /a(x)!'j')!'reduce'"
REDUCE = "(/a(x)!'i', /b(y)!'j')!'r'"


class _Recorder:
    """Every DNS lookup and every request that reaches the (mocked) socket layer."""

    def __init__(self) -> None:
        self.dns: list[str] = []
        self.requests: list[str] = []

    async def resolver(self, host: str, port: int) -> list[str]:
        self.dns.append(host)
        return ["93.184.216.34"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(f"{request.method} {request.url.host}{request.url.path}")
        return httpx.Response(200, text="PEER-REACHED")


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder()
    monkeypatch.setattr(gt, "_inner_transport", lambda: httpx.MockTransport(recorder.handler))
    return recorder


def _world(rec: _Recorder, peers: str, *, default_processor: str | None = None) -> Url4Node:
    """The engine's shape: a node used as the run's io, its outbound the guarded transport."""
    io = HttpIOLayer(guard=SourceGuard(peer_hosts=PEERS[peers]), resolver=rec.resolver)
    node = Url4Node("n1", outbound=io, default_processor=default_processor)
    node.endpoint("/a")(lambda r: "A")
    node.endpoint("/b")(lambda r: "B")
    return node


def test_the_hook_is_public_on_url4_dag() -> None:
    assert "refuse_remote_nodes" in url4.dag.__all__


@pytest.mark.asyncio
@pytest.mark.parametrize("peers", sorted(PEERS))
@pytest.mark.parametrize(
    ("expression", "processor"),
    [(REMOTE, None), (ENSEMBLE, None), (REDUCE, "url4://n2.example/v1")],
    ids=["remote-call", "ensemble-member", "url4-reduce-processor"],
)
async def test_the_hook_refuses_before_any_dns_or_request(
    rec: _Recorder, peers: str, expression: str, processor: str | None
) -> None:
    world = _world(rec, peers, default_processor=processor)
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(expression, world))
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert rec.dns == []
    assert rec.requests == []


@pytest.mark.asyncio
async def test_without_the_hook_a_bare_run_reaches_an_allowlisted_peer(rec: _Recorder) -> None:
    # WHY: the gap the hook closes (probe "Gap B", 2026-11-02); bare run() is not a node context.
    result = await run(REMOTE, _world(rec, "populated"))
    assert "PEER-REACHED" in result
    assert rec.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("peers", sorted(PEERS))
async def test_a_local_run_under_the_hook_is_unchanged(rec: _Recorder, peers: str) -> None:
    assert await refuse_remote_nodes(run(REDUCE, _world(rec, peers))) == "A"
    assert rec.dns == []
    assert rec.requests == []
