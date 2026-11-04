"""A ``url4://`` reduce processor is a remote-node call: refused in a node context (#1450 F1b).

FEATURE: file inputs for url4 (epic ``OME-1529``, unit ``OME-1539``); the remote-node half of F1b.
STORY: as a node operator, no ``processor=`` a caller sends, no ``default_processor`` I configure
and no expression that computes a processor can make my node call another node; each fails
``x.remote_node_unsupported`` before any DNS lookup or connection.

INVARIANT (Gap A, found by our own probe 2026-11-02): a fan-out reduce dispatches
``<processor>?q=()!<reducer input>``. When the processor resolves to ``url4://authority/path`` that
is an intent-processor call AT ANOTHER NODE, the same remote-node call a remote expression is, so
it is refused under BOTH an empty and a populated peer allowlist, with zero DNS and zero requests.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest

import url4.io._guarded_transport as gt
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._run import run
from url4.io._source_policy import SourceGuard
from url4.io.http import HttpIOLayer
from url4.peer.server import Url4Node

# WHY /v1: the eval path; a registered endpoint path would call that endpoint, not evaluate.
REDUCE = "(/a(x)!'i', /b(y)!'j')!'r'"
PEERS = {"empty": frozenset(), "populated": frozenset({"n1", "n2.example"})}


class _Recorder:
    """Records every DNS lookup and every request that reaches the (mocked) socket layer."""

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


def _node(rec: _Recorder, peers: str, *, default_processor: str | None = None) -> Url4Node:
    io = HttpIOLayer(guard=SourceGuard(peer_hosts=PEERS[peers]), resolver=rec.resolver)
    node = Url4Node("n1", outbound=io, default_processor=default_processor)
    node.endpoint("/a")(lambda r: "A")
    node.endpoint("/b")(lambda r: "B")
    return node


async def _assert_refused(call: Callable[[], Awaitable[object]], rec: _Recorder) -> None:
    with pytest.raises(ResolutionError) as info:
        await call()
    assert info.value.code == ErrorCode.REMOTE_NODE_UNSUPPORTED
    assert info.value.permanent is True
    # INVARIANT: refused BEFORE any I/O — no DNS lookup, no connection, no request.
    assert rec.dns == []
    assert rec.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("peers", sorted(PEERS))
@pytest.mark.parametrize(
    "processor",
    ["url4://n2.example/v1", "URL4://n2.example/v1", "url4://n2.example", "url4://n1/v1"],
)
async def test_a_callers_url4_processor_is_refused_before_any_io(
    rec: _Recorder, peers: str, processor: str
) -> None:
    node = _node(rec, peers)
    await _assert_refused(
        lambda: node.fetch(f"/v1?processor={processor}&q={REDUCE}", relative=True), rec
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("peers", sorted(PEERS))
async def test_a_url4_default_processor_is_refused_before_any_io(
    rec: _Recorder, peers: str
) -> None:
    node = _node(rec, peers, default_processor="url4://n2.example/v1")
    await _assert_refused(lambda: node.evaluate(REDUCE), rec)
    await _assert_refused(lambda: node.fetch(f"/v1?q={REDUCE}", relative=True), rec)


@pytest.mark.asyncio
@pytest.mark.parametrize("peers", sorted(PEERS))
async def test_an_expression_computed_url4_processor_is_refused_before_any_io(
    rec: _Recorder, peers: str
) -> None:
    # WHY: Form 3 (§27.3) evaluates to a URI and is reclassified; the check runs on the result.
    node = _node(rec, peers, default_processor="(p:0:'url4://n2.example/v1')!'$p'")
    await _assert_refused(lambda: node.evaluate(REDUCE), rec)


@pytest.mark.asyncio
@pytest.mark.parametrize("peers", sorted(PEERS))
@pytest.mark.parametrize(("processor", "expected"), [(None, "A"), ("/b", "B"), ("b", "B")])
async def test_a_local_processor_still_reduces(
    rec: _Recorder, peers: str, processor: str | None, expected: str
) -> None:
    node = _node(rec, peers)
    query = f"processor={processor}&q={REDUCE}" if processor else f"q={REDUCE}"
    result = await node.fetch(f"/v1?{query}", relative=True)
    assert getattr(result, "text", result) == expected
    assert rec.dns == []
    assert rec.requests == []


@pytest.mark.asyncio
async def test_bare_run_is_not_a_node_context_and_still_dispatches_a_url4_processor() -> None:
    # WHY: F1b scopes the refusal to a node context; a bare library run() is unchanged.
    calls: list[tuple[str, bool]] = []

    class _Io:
        async def fetch(self, target: str, *, relative: bool) -> str:
            calls.append((target, relative))
            return "REDUCED" if target.startswith("url4://") else target

    result = await run(REDUCE, _Io(), processor="url4://n2.example/v1")
    assert str(getattr(result, "text", result)) == "REDUCED"
    assert [c for c in calls if c[0].startswith("url4://n2.example/v1")][0][1] is False
