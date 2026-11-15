"""The fail-closed fallback reads each field and every decode round on its own (OME-1811 r12).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, quote characters cannot hide a ``url4://`` call from the remote-node
precheck's fail-closed fallback: not a quote run that would span two of a call's fields if they
were joined, not an encoded quote (``%27``) that only becomes a quote once decoded, and not a
URI that only appears after the second decode round.

INVARIANT (PR #1750 round 12, security review): the fallback scans the path, the verbatim
context and each param value separately; per field it scans the raw text (single-quote runs
blanked, as the grammar reads them) and EVERY decode round (never blanked: a quote that decoding
produced is not a quote the grammar would read), and takes the union. Each refusal comes with
zero endpoint invocations, zero DNS lookups and zero requests.
"""

from __future__ import annotations

import httpx
import pytest

import url4.io._guarded_transport as gt
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import refuse_remote_nodes, run
from url4.dag.node import DagNode
from url4.dag.nodes import RelUrlNode, TextNode
from url4.io._source_policy import SourceGuard
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest, FetchResult, IOLayer
from url4.peer.server import Url4Node

REMOTE = "url4://n2.example/v1"
REMOTE_TWICE_ENCODED = "url4%253A%252F%252Fn2.example%252Fv1"  # url4:// only after round 2


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


async def _assert_refused(target: str | DagNode, io: IOLayer, wire: _Tripwire) -> None:
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(target, io, processor="/a"))
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert (wire.calls, wire.dns, wire.requests) == ([], [], [])


@pytest.mark.asyncio
async def test_a_quote_run_spanning_two_fields_does_not_hide_a_url4_call(wire: _Tripwire) -> None:
    # WHY a pre-built call: the grammar keeps a quote out of a path, so only a hand-built node
    # (run() accepts one) can open a quote in the path and close it in the context. Joined, the
    # two would read as one quote run around the URI; field by field, the context names it.
    call = RelUrlNode(
        "/v1'",
        context=f"see {REMOTE} now'",
        is_expr=True,
        deps={"intent": TextNode("k")},
    )
    await _assert_refused(call, _NoEvalPort(_node(wire)), wire)


@pytest.mark.asyncio
async def test_an_encoded_quote_around_a_url4_call_does_not_hide_it(wire: _Tripwire) -> None:
    expression = f"(/a(x)!'q', ('v1')*(/$item?q=%27{REMOTE}%27)!'per')!'m'"
    await _assert_refused(expression, _node(wire), wire)


@pytest.mark.asyncio
async def test_a_url4_call_visible_only_after_the_second_decode_round_refuses(
    wire: _Tripwire,
) -> None:
    expression = f"(/a(x)!'q', ('v1')*(/$item?q=%2527{REMOTE_TWICE_ENCODED}%2527)!'per')!'m'"
    await _assert_refused(expression, _node(wire), wire)
