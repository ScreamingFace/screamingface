"""Under a node policy the remote precheck reads the compiled graph, never the scan (OME-1811).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, every ``url4://`` call a run would make is refused before my node runs
anything for it — wherever the text puts it: an iteration's per-row intent, a map inside a map,
a holdings context sent to my own evaluation path — and a run the precheck cannot check because
it is nested too deep is refused with a coded error, never run unchecked.

INVARIANT (PR #1750 round 7, owner decision "always compile"): under
:func:`url4.dag.refuse_remote_nodes` the precheck compiles the run text as ``run()`` does and
every fragment as the spawn hook does, and walks the graphs; the strict scan is no shortcut. Each
refused case fails ``x.remote_node_unsupported`` (permanent) with zero endpoint invocations, zero
DNS lookups and zero requests; each control runs; a too-deep compile is ``malformed_source``.
"""

from __future__ import annotations

import httpx
import pytest

import url4.dag._remote_walk as remote_walk
import url4.io._guarded_transport as gt
from url4.core.errors import ErrorCode, ParseError, ResolutionError
from url4.core.nodes import Node as AstNode
from url4.dag import refuse_remote_nodes, run
from url4.dag.compiler import Graph, LoweringRegistry
from url4.io._source_policy import SourceGuard
from url4.io.http import HttpIOLayer
from url4.peer.server import Url4Node

REMOTE = "url4://n2.example/v1"
ROW_INTENT = f"/c({REMOTE}(a)!'z')!'k'"  # a per-row intent that calls another node
REFUSED = {
    "per-row-intent": f"('r1','r2')*(/b($item)!'i')!{ROW_INTENT}",
    "per-row-intent-over-https-rows": f"https://rows*(/b($item)!'i')!{ROW_INTENT}",
    "per-row-intent-in-a-group": f"(/a(x)!'q', ('r1','r2')*(/b($item)!'i')!{ROW_INTENT})!'m'",
    "per-row-intent-of-a-map-in-a-map": (
        f"('s1','s2')*(('r1','r2')*(/b($item)!'i')!{ROW_INTENT})!'o'"
    ),
    "holdings-context-to-the-eval-path": f"(/a(x)!'q', /v1(@, {REMOTE}(y)!'i')!'k')!'m'",
}
# INVARIANT: every remote call the run would make, wherever it sits, is found before any I/O.
CORPUS = [
    f"{REMOTE}(a)!'i'",
    f"(/a(x)!'q', {REMOTE}(a)!'k')!'m'",
    f"(/a(x)!'q', (/b(y)!'w', {REMOTE}(a)!'k')!'h')!'m'",
    f"https://rows*({REMOTE}($item)!'i')!'per'",
    f"https://rows*(/b($item)!'i')!{ROW_INTENT}",
    f"(('r1','r2')*(/b($item)!'i')!'p')*({REMOTE}($item)!'i')!'p'",
    f"/c({REMOTE}(a)!'z')!'k'",
    f"/c((/b(y)!'w', {REMOTE}(a)!'z')!'g')!'k'",
    f"(/a(x)!'q', (('r1','r2')*({REMOTE}($item)!'i'))!'g')!'m'",
    f"(/a(x)!'q', x:({REMOTE}(a)!'z')!'g', $x)!'m'",
    f"https://rows*(/b($item)!'i', ('s1')*({REMOTE}($item)!'x')!'y')!'per'",
    f"(/a(x)!'q', /v1(@, {REMOTE}(y)!'i')!'k')!'m'",
]
CONTROLS = {
    "per-row-intent": "('r1','r2')*(/b($item)!'i')!/c(/a(a)!'z')!'k'",
    "quoted-url4-in-a-per-row-intent": f"('r1','r2')*(/b($item)!'i')!'see {REMOTE}'",
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
    guard = SourceGuard(peer_hosts=frozenset({"n2.example", "rows"}))
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


async def _assert_refused_for_free(expression: str, wire: _Tripwire) -> None:
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(expression, _world(wire)))
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert (wire.calls, wire.dns, wire.requests) == ([], [], [])


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(REFUSED))
async def test_a_remote_call_the_scan_misses_refuses_before_any_io(
    wire: _Tripwire, case: str
) -> None:
    await _assert_refused_for_free(REFUSED[case], wire)


@pytest.mark.asyncio
@pytest.mark.parametrize("expression", CORPUS)
async def test_the_precheck_finds_every_remote_call_the_run_makes(
    wire: _Tripwire, expression: str
) -> None:
    await _assert_refused_for_free(expression, wire)


@pytest.mark.asyncio
@pytest.mark.parametrize("expression", CORPUS)
async def test_every_corpus_text_does_call_the_remote_node_without_a_policy(
    wire: _Tripwire, expression: str
) -> None:
    # WHY: proves each corpus text really makes the call (the peer is reached, or the node's own
    # evaluation refuses it), so the refusals above are not refusals of dead text.
    try:
        await run(expression, _world(wire))
    except ResolutionError as exc:
        assert exc.code == ErrorCode.REMOTE_NODE_UNSUPPORTED  # the eval path is itself a node
        return
    assert "GET n2.example" in wire.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(CONTROLS))
async def test_the_same_shape_without_a_remote_call_runs(wire: _Tripwire, case: str) -> None:
    await refuse_remote_nodes(run(CONTROLS[case], _world(wire)))
    assert wire.calls  # local sources ran
    assert all("n2.example" not in request for request in wire.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("bare_root_ok", [False, True], ids=["run-text", "fragment"])
async def test_a_text_too_deep_to_compile_is_refused_coded_before_any_io(
    wire: _Tripwire, monkeypatch: pytest.MonkeyPatch, bare_root_ok: bool
) -> None:
    # INVARIANT (FAIL CLOSED): the stack running out while the precheck compiles is never "no
    # calls"; once a run text at one exact depth overflowed only inside the precheck and ran.
    real = remote_walk.compile_expression

    def too_deep(
        text: str | AstNode, *, registry: LoweringRegistry | None = None, bare_root_ok: bool = False
    ) -> Graph:
        if bare_root_ok is overflow_on:
            raise RecursionError("maximum recursion depth exceeded")
        return real(text, registry=registry, bare_root_ok=bare_root_ok)

    overflow_on = bare_root_ok
    monkeypatch.setattr(remote_walk, "compile_expression", too_deep)
    expression = "(/a(x)!'q', (('r1','r2')*(/b($item)!'i'))!'g')!'m'"  # no remote call at all
    with pytest.raises(ParseError) as caught:
        await refuse_remote_nodes(run(expression, _world(wire)))
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.MALFORMED_SOURCE, True)
    assert (wire.calls, wire.dns, wire.requests) == ([], [], [])


@pytest.mark.asyncio
async def test_a_descriptor_body_with_a_stray_quote_is_a_coded_row_error(wire: _Tripwire) -> None:
    # WHY: this body once raised a raw AssertionError out of the grammar (descriptor_head), which
    # escaped a node-policy run; it is a malformed source, reported as data like any bad row.
    expression = "https://rows*({\"k\":\"it's\"}, /p/it's)!'per'"
    result = await refuse_remote_nodes(run(expression, _world(wire)))
    assert "AssertionError" not in str(result)
    assert wire.requests == ["GET rows"]
