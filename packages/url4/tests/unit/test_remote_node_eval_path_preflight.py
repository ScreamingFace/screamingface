"""A call to the node's own eval path is prechecked as the eval path will run it (OME-1811).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run that hands my own eval path (``/v1``) an expression which calls
another node — in a context that is prose to the strict grammar but an iteration once the eval
path appends its intent, or through a ``processor=`` param — is refused before my node runs
anything.

INVARIANT (PR #1750 round 10, owner: "compile each /v1 call exactly the way /v1 will run it"):
under :func:`url4.dag.refuse_remote_nodes`, every relative call the io world routes to its eval
path is rebuilt with the node's own dispatch code (``Url4Node.eval_expression``: the reassembled
``(context)!intent`` plus its param chain) and walked; its ``processor=`` value is a ``maybe``
call like the run option. Each refused case fails ``x.remote_node_unsupported`` (permanent) with
zero endpoint invocations, zero DNS lookups and zero requests, and a map body raises rather than
completing with error rows. The same context to a normal route is text and runs.
KNOWN LIMIT (owner-accepted 2026-11-14): text that becomes an expression only inside the eval
path (a quoted literal, a ``$name`` value) is checked by the inner run, after siblings ran.
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
ITERATION = f"'r1' *({REMOTE}($item)!'i') zz(y)!'p'"  # prose until /v1 appends its intent
REFUSED = {
    "iteration-context-to-the-eval-path": f"(/a(x)!'q', /v1({ITERATION})!'k')!'m'",
    "iteration-context-beside-a-local-member": (
        f"(/a(x)!'q', (/b(y)!'w', /v1({ITERATION})!'k')!'h')!'m'"
    ),
    "iteration-context-in-a-map-body": (f"('r1','r2')*(/b($item)!'i', /v1({ITERATION})!'k')!'per'"),
    "unquoted-collection-context": (
        f"(/a(x)!'q', /v1(hello *({REMOTE}($item)!'i') world(y)!'p')!'k')!'m'"
    ),
    "processor-param-on-the-call": (
        f"(/a(x)!'q', /v1(/b(y)!'w', /c(z)!'v')!'k';processor={REMOTE})!'m'"
    ),
    "processor-param-in-the-query": (
        f"(/a(x)!'q', /v1?processor={REMOTE}&q=(/b(y)!'w', /c(z)!'v')!'k')!'m'"
    ),
    "eval-path-collection-qualifier": f"(/a(x)!'q', /v1/shelf({ITERATION})!'k')!'m'",
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


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Tripwire:
    tripwire = _Tripwire()
    monkeypatch.setattr(gt, "_inner_transport", lambda: httpx.MockTransport(tripwire.handler))
    return tripwire


def _world(wire: _Tripwire) -> Url4Node:
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


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(REFUSED))
async def test_an_eval_path_call_is_prechecked_as_the_eval_path_runs_it(
    wire: _Tripwire, case: str
) -> None:
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(REFUSED[case], _world(wire)))
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert (wire.calls, wire.dns, wire.requests) == ([], [], [])


@pytest.mark.asyncio
async def test_the_same_context_to_a_normal_route_is_text_and_runs(wire: _Tripwire) -> None:
    await refuse_remote_nodes(run(f"(/a(x)!'q', /c({ITERATION})!'k')!'m'", _world(wire)))
    assert sorted(wire.calls) == ["a", "a", "c"]
    assert wire.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expression",
    [
        "(/a(x)!'q', /v1(/b(y)!'w')!'k')!'m'",
        "(/a(x)!'q', /v1(/b(y)!'w', /c(z)!'v')!'k';processor=/a)!'m'",
    ],
    ids=["plain", "local-processor"],
)
async def test_an_eval_path_call_with_no_remote_node_runs(wire: _Tripwire, expression: str) -> None:
    await refuse_remote_nodes(run(expression, _world(wire)))
    assert "b" in wire.calls  # the inner run's member ran on this node
    assert wire.requests == []
