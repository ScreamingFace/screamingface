"""The fail-closed fallback reads a call's text as the eval path decodes it (OME-1811 round 12).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, percent-encoding (or ``+``-encoding) a ``url4://`` call into the
``q=`` of a call whose route is computed (``/$item?q=…``), or that runs on an io without the
eval-path port, does not slip it past the remote-node precheck.

INVARIANT (PR #1750 round 12): when the precheck cannot ask what the eval path runs (a computed
route, or no ``eval_expression`` port), the call's static text is ``unquote_plus``-decoded until
it stops changing (bounded) — the eval path decodes ``q=`` the same way — before its unquoted
``url4://`` URIs are read as ``maybe`` calls. Each refusal comes with zero endpoint invocations,
zero DNS lookups and zero requests, and a map body raises rather than completing.
"""

from __future__ import annotations

from urllib.parse import quote, quote_plus

import httpx
import pytest

import url4.io._guarded_transport as gt
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import refuse_remote_nodes, run
from url4.io._source_policy import SourceGuard
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest, FetchResult, IOLayer
from url4.peer.server import Url4Node

REMOTE = "url4://n2.example/v1"
ALONE = quote(f"({REMOTE}(x)!'k')!'j'", safe="")
BESIDE = f"(/b(y)!'w', {REMOTE}(x)!'k')!'j'"
COMPUTED_ROUTE = {
    "percent-encoded-in-a-map-body": f"('v1')*(/b($item)!'i', /$item?q={ALONE})!'per'",
    "percent-encoded-beside-a-local-member": (
        f"(/a(x)!'q', ('v1')*(/$item?q={quote(BESIDE, safe='')})!'per')!'m'"
    ),
    "plus-encoded": f"(/a(x)!'q', ('v1')*(/$item?q={quote_plus(BESIDE, safe='')})!'per')!'m'",
    "double-encoded": f"(/a(x)!'q', ('v1')*(/$item?q={quote(ALONE, safe='')})!'per')!'m'",
    # WHY a bound name, not a row: the route is computed outside any map body, so only the
    # computed-route fallback (static_target() is None) can see the call.
    "named-route": f"(p:0:'v1', /a(x)!'q', /$p?q={quote(BESIDE, safe='')})!'m'",
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
        self.requests.append(f"{request.method} {request.headers.get('host', '')}")
        return httpx.Response(
            200, text='["w1", "w2"]', headers={"content-type": "application/json"}
        )


class _NoEvalPort:
    """A bare io wrapper that forwards fetching but not the eval-path port."""

    def __init__(self, inner: Url4Node) -> None:
        self._inner = inner

    async def fetch(self, target: str, *, relative: bool) -> str:
        return await self._inner.fetch(target, relative=relative)

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        return await self._inner.fetch_ex(request)


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Tripwire:
    tripwire = _Tripwire()
    monkeypatch.setattr(gt, "_inner_transport", lambda: httpx.MockTransport(tripwire.handler))
    return tripwire


def _node(wire: _Tripwire) -> Url4Node:
    guard = SourceGuard(peer_hosts=frozenset({"n2.example"}))
    io = HttpIOLayer(guard=guard, resolver=wire.resolver)
    node = Url4Node("n1", outbound=io)

    def endpoint(name: str):
        def handle(request: object) -> str:
            wire.calls.append(name)  # the tripwire: a local source that ran
            return name.upper()

        return handle

    for name in ("a", "b", "c"):
        node.endpoint(f"/{name}")(endpoint(name))
    return node


async def _assert_refused(expression: str, io: IOLayer, wire: _Tripwire) -> None:
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(expression, io, processor="/a"))
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert (wire.calls, wire.dns, wire.requests) == ([], [], [])


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(COMPUTED_ROUTE))
async def test_an_encoded_url4_call_on_a_computed_route_refuses_before_any_io(
    wire: _Tripwire, case: str
) -> None:
    await _assert_refused(COMPUTED_ROUTE[case], _node(wire), wire)


@pytest.mark.asyncio
async def test_an_encoded_url4_call_on_an_io_without_the_port_refuses_before_any_io(
    wire: _Tripwire,
) -> None:
    expression = f"('r1','r2')*(/b($item)!'i', /v1?q={quote(BESIDE, safe='')})!'per'"
    await _assert_refused(expression, _NoEvalPort(_node(wire)), wire)


@pytest.mark.asyncio
async def test_an_encoded_call_naming_no_url4_still_runs(wire: _Tripwire) -> None:
    encoded = quote("(/b(y)!'w')!'j'", safe="")
    await refuse_remote_nodes(
        run(f"(/a(x)!'q', ('v1')*(/$item?q={encoded})!'per')!'m'", _node(wire))
    )
    assert "b" in wire.calls  # the row reached the eval path and ran there
    assert wire.requests == []
