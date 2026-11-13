"""A remote node beside or inside a grammar-blind nested group still refuses first (OME-1811).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run whose text holds a nested group the strict grammar rejects but
the engine compiles (``(('r1','r2')*(/b($item)!'i'))!'g'``: a bare iteration whose intent sits
outside it) is still refused before my node runs anything, when it names another node.

INVARIANT (PR #1750 round 5): under :func:`url4.dag.refuse_remote_nodes`, a ``url4://`` call the
run-start precheck cannot see through the strict parse (the whole text, a deferred group or a map
body segment fails it) is found by a compiled-graph walk instead, and fails
``x.remote_node_unsupported`` (permanent) with zero endpoint invocations, zero DNS lookups and zero
requests. The same shapes without the remote call run normally.
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
BLIND = "(('r1','r2')*(/b($item)!'i'))!'g'"  # strict grammar: no per-row intent; spawn: fine
BLIND_HTTPS = "(https://rows*(/b($item)!'i'))!'g'"
REFUSED = {
    "remote-sibling-of-the-group": f"(/a(x)!'q', {BLIND}, {REMOTE}(a)!'k')!'m'",
    "remote-inside-the-group": (
        f"(/a(x)!'q', (('r1','r2')*(/b($item)!'i', {REMOTE}(a)!'k'))!'g')!'m'"
    ),
    "remote-in-a-sibling-map-body": (
        f"(/a(x)!'q', {BLIND}, ('s1','s2')*({REMOTE}($item)!'j')!'p')!'m'"
    ),
    "https-collection-group-with-a-remote-sibling": (
        f"(/a(x)!'q', {BLIND_HTTPS}, {REMOTE}(a)!'k')!'m'"
    ),
    "remote-in-a-https-collection-group": (
        f"(/a(x)!'q', (https://rows*(/b($item)!'i', {REMOTE}(a)!'k'))!'g')!'m'"
    ),
    "group-in-a-valid-map-body": (
        f"https://rows*(/b($item)!'i', (('r1','r2')*({REMOTE}($item)!'x'))!'g')!'per'"
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
        self.requests.append(f"{request.method} {request.url.host}{request.url.path}")
        return httpx.Response(
            200, text='["w1", "w2"]', headers={"content-type": "application/json"}
        )


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Tripwire:
    tripwire = _Tripwire()
    monkeypatch.setattr(gt, "_inner_transport", lambda: httpx.MockTransport(tripwire.handler))
    return tripwire


def _world(wire: _Tripwire, default_processor: str | None = None) -> Url4Node:
    guard = SourceGuard(peer_hosts=frozenset({"n2.example", "rows"}))
    io = HttpIOLayer(guard=guard, resolver=wire.resolver)
    node = Url4Node("n1", outbound=io, default_processor=default_processor)

    def endpoint(name: str):
        def handle(request: object) -> str:
            wire.calls.append(name)  # the tripwire: a local source that ran
            return name.upper()

        return handle

    node.endpoint("/a")(endpoint("a"))
    node.endpoint("/b")(endpoint("b"))
    return node


def _assert_refused_for_free(
    caught: pytest.ExceptionInfo[ResolutionError], wire: _Tripwire
) -> None:
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert wire.calls == []
    assert wire.dns == []
    assert wire.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(REFUSED))
async def test_a_remote_call_the_strict_grammar_cannot_see_refuses_before_any_io(
    wire: _Tripwire, case: str
) -> None:
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(REFUSED[case], _world(wire)))
    _assert_refused_for_free(caught, wire)


@pytest.mark.asyncio
async def test_the_grammar_blind_group_alone_runs_normally(wire: _Tripwire) -> None:
    # WHY the control: proves the shape is runnable and the tripwire fires, so the empty lists
    # above mean "refused first", not "the text never ran".
    await refuse_remote_nodes(run(f"(/a(x)!'q', {BLIND})!'m'", _world(wire)))
    assert sorted(wire.calls) == ["a", "b", "b"]  # the member, then one call per row
    assert wire.requests == []


@pytest.mark.asyncio
async def test_the_https_collection_group_alone_fetches_its_rows(wire: _Tripwire) -> None:
    await refuse_remote_nodes(run(f"(/a(x)!'q', {BLIND_HTTPS})!'m'", _world(wire)))
    assert wire.dns == ["rows"]
    assert wire.requests == ["GET 93.184.216.34/"]
    assert wire.calls.count("b") == 2  # one per fetched row


@pytest.mark.asyncio
async def test_a_bare_run_is_not_prechecked(wire: _Tripwire) -> None:
    # INVARIANT: without a policy nothing is prechecked: the local member still runs.
    await run(f"(/a(x)!'q', {BLIND}, {REMOTE}(a)!'k')!'m'", _world(wire))
    assert "a" in wire.calls


@pytest.mark.asyncio
async def test_a_non_reducing_run_refuses_a_static_form_3_url4_processor(wire: _Tripwire) -> None:
    # INVARIANT (round 4 merge widening, pinned): the run's static Form-3 processor value is a
    # ``maybe`` call refused at run start on EVERY run, a non-reducing one included.
    world = _world(wire, f"(p:0:'{REMOTE}')!'$p'")
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run("/a(x)!'i'", world))
    _assert_refused_for_free(caught, wire)
