"""A remote node in a deferred group inside a local call's context refuses first (OME-1811).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run that hides another node's call in a grammar-blind group inside a
local call's context (``/c((('r1','r2')*(url4://…($item)!'i'))!'g')!'k'``) — which the lowering
defers into a caller-side group that runs HERE — is refused before my node runs anything; a
quoted mention of ``url4://`` or a prose context is never mistaken for a call; and a deeply
nested run is walked without blowing the stack.

INVARIANT (PR #1750 round 6): under :func:`url4.dag.refuse_remote_nodes` each refused case fails
``x.remote_node_unsupported`` (permanent) with zero endpoint invocations, zero DNS lookups and
zero requests, whether the context sits in the run text, a map body, a nested group or a Form-3
processor. Each control runs as it did before the precheck existed.
"""

from __future__ import annotations

import httpx
import pytest

import url4.io._guarded_transport as gt
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import refuse_remote_nodes, run
from url4.dag.compiler import Graph, LoweringRegistry
from url4.io._source_policy import SourceGuard
from url4.io.http import HttpIOLayer
from url4.peer.server import Url4Node

REMOTE = "url4://n2.example/v1"
CTX = f"/c((('r1','r2')*({REMOTE}($item)!'i'))!'g')!'k'"  # the blind group is /c's context
REDUCE = "(/a(x)!'i', /b(y)!'j')!'r'"
DEPTH = 300


def _deep(bottom: str) -> str:
    """``DEPTH`` nested lazy groups beside a grammar-blind one, ``bottom`` innermost."""
    text = bottom
    for _ in range(DEPTH):
        text = f"(/b(y)!'w', {text})!'h'"
    return f"(/a(x)!'q', (('r1')*(/b($item)!'i'))!'g', {text})!'m'"


REFUSED = {
    "context-in-the-run-text": (f"(/a(x)!'q', {CTX})!'m'", None),
    "context-beside-a-local-member-in-the-group": (
        f"/c((('r1','r2')*(/b($item)!'i', {REMOTE}($item)!'z'))!'g')!'k'",
        None,
    ),
    "context-in-a-map-body": (f"https://rows*(/b($item)!'i', {CTX})!'per'", None),
    "context-in-a-nested-group": (f"(/a(x)!'q', (/b(y)!'w', {CTX})!'h')!'m'", None),
    "context-in-a-form-3-processor": (REDUCE, f"(p:0:{CTX})!'$p'"),
    "remote-at-the-bottom-of-a-deep-run": (_deep(f"{REMOTE}(a)!'k'"), None),
    "unquoted-url4-in-an-uncompilable-body-over-no-rows": (
        f"https://empty*(/b($item)!'i', {REMOTE}($item)!'x' junk)!'per'",
        None,
    ),
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
        host = request.headers.get("host", "")
        self.requests.append(f"{request.method} {host}")
        rows = "[]" if host == "empty" else '["w1", "w2"]'
        return httpx.Response(200, text=rows, headers={"content-type": "application/json"})


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Tripwire:
    tripwire = _Tripwire()
    monkeypatch.setattr(gt, "_inner_transport", lambda: httpx.MockTransport(tripwire.handler))
    return tripwire


def _world(wire: _Tripwire, default_processor: str | None = None) -> Url4Node:
    # WHY the Host header: every host pins to one address, so it tells `rows` from `empty`.
    guard = SourceGuard(peer_hosts=frozenset({"n2.example", "rows", "empty"}))
    io = HttpIOLayer(guard=guard, resolver=wire.resolver)
    node = Url4Node("n1", outbound=io, default_processor=default_processor)

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
async def test_a_remote_call_a_call_context_hides_refuses_before_any_io(
    wire: _Tripwire, case: str
) -> None:
    expression, processor = REFUSED[case]
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(expression, _world(wire, processor)))
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert wire.calls == []
    assert wire.dns == []
    assert wire.requests == []


@pytest.mark.asyncio
async def test_the_same_context_without_a_remote_call_runs(wire: _Tripwire) -> None:
    await refuse_remote_nodes(
        run("(/a(x)!'q', /c((('r1','r2')*(/b($item)!'i'))!'g')!'k')!'m'", _world(wire))
    )
    assert sorted(wire.calls) == ["a", "a", "b", "b", "c"]  # the reduce runs on route /a


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", ["empty", "rows"])
async def test_a_quoted_url4_mention_in_an_uncompilable_body_is_not_a_call(
    wire: _Tripwire, rows: str
) -> None:
    # WHY: quoted text is data, never a call (C4); the run behaves exactly as without a policy.
    body = f"/b($item)!'i', /b($item)!'see {REMOTE}' junk"
    await refuse_remote_nodes(run(f"https://{rows}*({body})!'per'", _world(wire)))
    assert wire.requests == [f"GET {rows}"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context",
    ["hello there, my friend", f"see {REMOTE} for docs, thanks"],
    ids=["plain-prose", "prose-mentioning-url4"],
)
async def test_a_prose_context_is_shipped_and_never_refused(wire: _Tripwire, context: str) -> None:
    # INVARIANT: an unparseable context is prose, shipped verbatim to the route (never run here),
    # so it adds no call, whatever text it holds.
    await refuse_remote_nodes(run(f"(/a(x)!'q', /c({context})!'k')!'m'", _world(wire)))
    assert sorted(wire.calls) == ["a", "a", "c"]  # the reduce runs on route /a
    assert wire.requests == []


@pytest.mark.asyncio
async def test_a_deep_run_without_a_remote_call_runs_under_the_policy(wire: _Tripwire) -> None:
    # WHY: the walk is iterative; once a 300-deep run escaped run() as a raw RecursionError.
    await refuse_remote_nodes(run(_deep("/b(z)!'k'"), _world(wire)))
    assert wire.calls.count("a") == 2  # the member and the outer reduce
    assert wire.calls.count("b") == DEPTH + 2  # one per level, the row, and the bottom call


@pytest.mark.asyncio
async def test_a_fragment_too_deep_to_compile_fails_closed_with_a_coded_refusal(
    wire: _Tripwire, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT (FAIL CLOSED): a fragment the walk cannot compile because the stack ran out is
    # read like any uncompilable one — its unquoted url4:// URIs are refused, coded and before
    # any I/O — never a raw RecursionError and never call-free.
    import url4.dag._remote_walk as walk

    real = walk.compile_expression

    def too_deep(
        text: str, *, registry: LoweringRegistry | None = None, bare_root_ok: bool = False
    ) -> Graph:
        if bare_root_ok:
            raise RecursionError("maximum recursion depth exceeded")
        return real(text, registry=registry, bare_root_ok=bare_root_ok)

    monkeypatch.setattr(walk, "compile_expression", too_deep)
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(f"(/a(x)!'q', {CTX})!'m'", _world(wire)))
    assert caught.value.code == ErrorCode.REMOTE_NODE_UNSUPPORTED
    assert (wire.calls, wire.dns, wire.requests) == ([], [], [])
