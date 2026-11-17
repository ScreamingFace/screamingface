"""Without the eval-path port, or without a static route, a call is read fail closed (OME-1811).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, wrapping my node's io in a layer that does not forward the eval-path
port, or naming a call's route through ``$item``, never switches the remote-node precheck off:
a ``url4://`` call such a call could hand my eval path refuses the run before anything runs.

INVARIANT (PR #1750 round 11, owner decision "fail closed"): under
:func:`url4.dag.refuse_remote_nodes`, a relative call whose eval-path text the precheck cannot
ask for — the io in hand lacks ``eval_expression``, or the route needs a run-time value — has
every unquoted ``url4://`` URI in its static text (path, verbatim context, params) read as a
``maybe`` call: refused with zero endpoint invocations, DNS lookups and requests. A call naming
none runs as before.
"""

from __future__ import annotations

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
ITERATION = f"'r1' *({REMOTE}($item)!'i') zz(y)!'p'"
WITHOUT_THE_PORT = {
    "iteration-context-to-the-eval-path": f"(/a(x)!'q', /v1({ITERATION})!'k')!'m'",
    "iteration-context-beside-a-local-member": (
        f"(/a(x)!'q', (/b(y)!'w', /v1({ITERATION})!'k')!'h')!'m'"
    ),
    "iteration-context-in-a-map-body": f"('r1','r2')*(/b($item)!'i', /v1({ITERATION})!'k')!'per'",
    "processor-param-on-the-call": (
        f"(/a(x)!'q', /v1(/b(y)!'w', /c(z)!'v')!'k';processor={REMOTE})!'m'"
    ),
    "processor-param-in-the-query": (
        f"(/a(x)!'q', /v1?processor={REMOTE}&q=(/b(y)!'w', /c(z)!'v')!'k')!'m'"
    ),
}
# WHY these are pins, not fixes: the path grammar already refuses a `$` in an expression path
# when the row runs; the precheck must still read them fail closed, never as call-free.
DYNAMIC_ROUTE = {
    "bare-uri-with-a-processor": f"('v1')*(/$item?processor={REMOTE}&q=(/b(y)!'w')!'k')!'per'",
    "v-dollar-item-with-an-iteration": f"('1')*(/v$item({ITERATION})!'k')!'per'",
    "v-dollar-item-with-a-processor": f"('1')*(/v$item(/b(y)!'w')!'k';processor={REMOTE})!'per'",
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
@pytest.mark.parametrize("case", sorted(WITHOUT_THE_PORT))
async def test_an_io_without_the_eval_port_still_refuses_an_eval_path_call(
    wire: _Tripwire, case: str
) -> None:
    await _assert_refused(WITHOUT_THE_PORT[case], _NoEvalPort(_node(wire)), wire)


@pytest.mark.asyncio
async def test_an_io_without_the_eval_port_runs_a_call_naming_no_url4(wire: _Tripwire) -> None:
    io = _NoEvalPort(_node(wire))
    await refuse_remote_nodes(run("(/a(x)!'q', /v1(/b(y)!'w')!'k')!'m'", io, processor="/a"))
    assert "b" in wire.calls
    assert wire.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(DYNAMIC_ROUTE))
async def test_a_call_with_a_dynamic_route_is_read_fail_closed(wire: _Tripwire, case: str) -> None:
    await _assert_refused(DYNAMIC_ROUTE[case], _node(wire), wire)


@pytest.mark.asyncio
async def test_a_dynamic_route_naming_no_url4_runs_as_before(wire: _Tripwire) -> None:
    # The row fails on the path grammar, as without a policy; the run itself completes.
    result = await refuse_remote_nodes(run("('v1')*(/$item?q=(/b(y)!'w')!'k')!'per'", _node(wire)))
    assert "malformed_source" in result
    assert wire.requests == []
