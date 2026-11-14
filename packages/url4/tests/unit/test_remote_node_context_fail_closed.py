"""A verbatim context the precheck cannot compile is never read as call-free (OME-1811 round 9).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a holdings context (``@``) my node may evaluate, a context too deep
to compile, and a map body whose text happens to equal a prose context are all checked fail
closed: a ``url4://`` call they name refuses the run before my node runs anything.

INVARIANT (PR #1750 round 9, security review of 623e8305b): only TRUE prose — a verbatim context
with no holdings ref — may fall back to its scan, and only when its compile fails ordinarily. A
holdings context is a fragment: a failed compile adds its unquoted ``url4://`` URIs as ``maybe``
calls, and a too-deep one naming none is refused ``malformed_source``. A too-deep compile always
looks for URIs first, prose included. A map/lazy fragment never inherits prose mode from a
context with the same text. Each refusal comes with zero endpoint invocations, zero DNS lookups
and zero requests.
"""

from __future__ import annotations

import httpx
import pytest

import url4.dag._remote_walk as remote_walk
import url4.io._guarded_transport as gt
from url4.core.errors import ErrorCode, ParseError, ResolutionError, Url4Error
from url4.core.nodes import Node as AstNode
from url4.dag import refuse_remote_nodes, run
from url4.dag.compiler import Graph, LoweringRegistry
from url4.io._source_policy import SourceGuard
from url4.io.http import HttpIOLayer
from url4.peer.server import Url4Node

REMOTE = "url4://n2.example/v1"
HOLDINGS = f"@, {REMOTE}(y)!'i'"
PROSE = f"mail bob@x.io, {REMOTE}(a)!'x' junk"  # an '@' but no holdings ref; does not compile


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


def _overflow_on(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """Make the precheck's compile of exactly ``text`` run out of stack."""
    real = remote_walk.compile_expression

    def compile_expression(
        target: str | AstNode,
        *,
        registry: LoweringRegistry | None = None,
        bare_root_ok: bool = False,
    ) -> Graph:
        if target == text:
            raise RecursionError("maximum recursion depth exceeded")
        return real(target, registry=registry, bare_root_ok=bare_root_ok)

    monkeypatch.setattr(remote_walk, "compile_expression", compile_expression)


async def _refused(expression: str, wire: _Tripwire) -> Url4Error:
    with pytest.raises(Url4Error) as caught:
        await refuse_remote_nodes(run(expression, _world(wire)))
    assert (wire.calls, wire.dns, wire.requests) == ([], [], [])
    return caught.value


def _is_remote_refusal(error: Url4Error) -> bool:
    return isinstance(error, ResolutionError) and (error.code, error.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )


@pytest.mark.asyncio
async def test_a_holdings_context_that_does_not_compile_still_refuses_its_url4_call(
    wire: _Tripwire,
) -> None:
    error = await _refused(f"(/a(x)!'q', /v1({HOLDINGS} junk)!'k')!'m'", wire)
    assert _is_remote_refusal(error)


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [HOLDINGS, PROSE], ids=["holdings", "prose"])
async def test_a_context_too_deep_to_compile_refuses_the_url4_call_it_names(
    wire: _Tripwire, monkeypatch: pytest.MonkeyPatch, context: str
) -> None:
    _overflow_on(monkeypatch, f"({context})")
    error = await _refused(f"(/a(x)!'q', /v1({context})!'k')!'m'", wire)
    assert _is_remote_refusal(error)


@pytest.mark.asyncio
async def test_a_holdings_context_too_deep_to_compile_naming_no_url4_is_refused_coded(
    wire: _Tripwire, monkeypatch: pytest.MonkeyPatch
) -> None:
    _overflow_on(monkeypatch, "(@, /b(y)!'i')")
    error = await _refused("(/a(x)!'q', /v1(@, /b(y)!'i')!'k')!'m'", wire)
    assert isinstance(error, ParseError)
    assert (error.code, error.permanent) == (ErrorCode.MALFORMED_SOURCE, True)


@pytest.mark.asyncio
async def test_a_map_body_equal_to_a_prose_context_is_not_read_as_prose(wire: _Tripwire) -> None:
    # WHY: the map's fragment ``(PROSE)`` is the very text the /c context compiles as; once the
    # two shared one cache entry, so the fragment inherited the prose fallback (no calls).
    error = await _refused(f"(/a(x)!'q', /c({PROSE})!'k', (('r1')*({PROSE}))!'g')!'m'", wire)
    assert _is_remote_refusal(error)


@pytest.mark.asyncio
async def test_the_same_prose_context_alone_still_runs(wire: _Tripwire) -> None:
    # INVARIANT: true prose shipped to a normal route is text there, never a call (round-6 pin).
    await refuse_remote_nodes(run(f"(/a(x)!'q', /c({PROSE})!'k')!'m'", _world(wire)))
    assert "c" in wire.calls
    assert wire.requests == []
