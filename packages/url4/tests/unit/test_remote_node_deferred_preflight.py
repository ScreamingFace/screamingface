"""A refused remote node in a deferred fragment or a computed processor fails first (OME-1811).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run whose map body, deferred group or Form-3 processor names another
node fails before my node fetches the collection or runs any local sibling, and the failure can
never be folded into a successful result (an ``on_error=collect`` error row).

INVARIANT: under :func:`url4.dag.refuse_remote_nodes`, a ``url4://`` remote expression in a
statically present map body or deferred group, and a statically computable Form-3 processor that
computes a ``url4://`` URI, fail ``x.remote_node_unsupported`` (permanent) with zero endpoint
invocations, zero DNS lookups and zero requests. A processor computed from a fetched value is
still refused at run time, and a refusal a row policy swallowed still fails the run.
"""

from __future__ import annotations

import httpx
import pytest

import url4.io._guarded_transport as gt
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import refuse_remote_nodes, run
from url4.io._source_policy import SourceGuard
from url4.io.http import HttpIOLayer
from url4.observe import RunFinished
from url4.peer.server import Url4Node

REMOTE = "url4://n2.example/v1"
REDUCE = "(/a(x)!'i', /b(y)!'j')!'r'"
STATIC = {
    "map-body-over-a-fetched-collection": (f'https://rows*({REMOTE}($item)!"i")!"per"', None),
    "map-body-skip-policy": (
        f"(https://rows*({REMOTE}($item)!'i')!'per';iteration.on_error=skip)!'all'",
        None,
    ),
    "map-body-over-a-local-collection": (f"/a(x)!'c'*({REMOTE}($item)!'i')!'per'", None),
    "deferred-group-in-a-map-body": (
        f"https://rows*(/a($item)!'i', (/b(y)!'k', {REMOTE}(a)!'m')!'n')!'per'",
        None,
    ),
    "static-form-3-processor": (REDUCE, f"(p:0:'{REMOTE}')!'$p'"),
    "static-form-3-processor-positional": (REDUCE, f"('{REMOTE}')!'$1'"),
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
        rows = '["r1", "r2"]'
        return httpx.Response(200, text=rows, headers={"content-type": "application/json"})


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Tripwire:
    tripwire = _Tripwire()
    monkeypatch.setattr(gt, "_inner_transport", lambda: httpx.MockTransport(tripwire.handler))
    return tripwire


def _world(wire: _Tripwire, default_processor: str | None) -> Url4Node:
    guard = SourceGuard(peer_hosts=frozenset({"n2.example", "rows"}))
    io = HttpIOLayer(guard=guard, resolver=wire.resolver)
    node = Url4Node("n1", outbound=io, default_processor=default_processor)

    def endpoint(name: str, reply: str):
        def handle(request: object) -> str:
            wire.calls.append(name)  # the tripwire: a local source that ran
            return reply

        return handle

    node.endpoint("/a")(endpoint("a", '["A1", "A2"]'))
    node.endpoint("/b")(endpoint("b", "B"))
    node.endpoint("/p")(endpoint("p", REMOTE))  # a processor URI only a fetch can know
    return node


def _assert_refused(caught: pytest.ExceptionInfo[ResolutionError]) -> None:
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(STATIC))
async def test_a_static_remote_node_fails_before_any_outer_fetch_or_sibling(
    wire: _Tripwire, case: str
) -> None:
    expression, processor = STATIC[case]
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(expression, _world(wire, processor)))
    _assert_refused(caught)
    assert wire.calls == []
    assert wire.dns == []
    assert wire.requests == []


@pytest.mark.asyncio
async def test_the_tripwire_sees_the_outer_fetch_on_a_local_map(wire: _Tripwire) -> None:
    # WHY: proves `https://rows` is observed, so the empty lists above mean "never fetched".
    await refuse_remote_nodes(run("https://rows*(/b($item)!'i')!'per'", _world(wire, None)))
    assert wire.dns == ["rows"]
    assert wire.requests == ["GET 93.184.216.34/"]  # the pinned address of `rows`
    assert wire.calls.count("b") == 2  # one per row


@pytest.mark.asyncio
async def test_a_dynamic_form_3_processor_is_still_refused_at_run_time(wire: _Tripwire) -> None:
    # WHY the endpoints run here: the processor URI is a fetched value, unknowable before the run.
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(REDUCE, _world(wire, "(p:0:/p(x)!'i')!'$p'")))
    _assert_refused(caught)
    assert sorted(wire.calls) == ["a", "b", "p"]
    assert wire.dns == []
    assert wire.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["collect", "skip"])
async def test_a_dynamic_refusal_in_a_map_row_fails_the_run_not_the_row(
    wire: _Tripwire, policy: str
) -> None:
    # WHY a per-row reduce with a fetched processor: its refusal is only knowable inside a row,
    # and the row policy would otherwise fold it into an error row of a successful run.
    events: list[object] = []
    world = _world(wire, "(p:0:/p(x)!'i')!'$p'")
    rows = f"(https://rows*(/b($item)!'i', /b(y)!'j')!'r';iteration.on_error={policy})!'all'"
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(rows, world, observer=_Recorder(events)))
    _assert_refused(caught)
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status == "error"  # the run itself failed; not a later re-raise
    assert wire.requests == ["GET 93.184.216.34/"]  # only the collection, never the peer


class _Recorder:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    def on_event(self, event: object) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_a_dynamic_refusal_an_optional_guard_swallowed_still_fails_the_run(
    wire: _Tripwire,
) -> None:
    # WHY defence in depth: `;optional` turns the inner reduce's run-time refusal into a source
    # failure the outer group drops; the run must still fail rather than return "T".
    events: list[object] = []
    world = _world(wire, "(p:0:/p(x)!'i')!'$p'")
    guarded = "(t:'T', (/a(x)!'i', /b(y)!'j')!'r';optional)!'$t'"
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(guarded, world, observer=_Recorder(events)))
    _assert_refused(caught)
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status == "error"
    assert wire.requests == []


@pytest.mark.asyncio
async def test_a_bare_run_keeps_its_map_rows_and_processor_untouched(wire: _Tripwire) -> None:
    # INVARIANT: without a policy the preflight is a no-op: the collection still runs first.
    await run(f"/a(x)!'c'*({REMOTE}($item)!'i')!'per'", _world(wire, None))
    assert wire.calls[:1] == ["a"]  # the collection ran; the rows failed as data, not refused
