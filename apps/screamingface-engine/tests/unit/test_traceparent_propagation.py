"""The run's trace id travels from the engine onto every outbound aigateway request (OME-1119).

Sibling of `test_traceparent.py`, which pins the INBOUND half — how a caller's traceparent is
adopted and stamped onto the run's frames. This file pins the OUTBOUND half: the engine had
been a trace sink, adopting an id and telling nobody. The header set aigateway received during
the audit was `Host, Accept, Accept-Encoding, Connection, User-Agent, X-User-Email, X-Profile,
Content-Length, Content-Type` — no traceparent on any of three client paths.

Rung 2 of the correlation ladder (`packages/screamingface/tests/e2e/test_correlation_chain.py`)
is the end-to-end statement of the same claim; these are the engine-side unit tests that say
*why* it holds and pin the two boundaries an e2e run cannot reach:

- a run whose caller sent NO inbound traceparent still propagates the id url4 minted, and
- two runs sharing one cached world do not share one trace id.

The second is the reason this is a ContextVar rather than a constructor argument.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

import httpx
import pytest
from starlette.requests import Request

from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import Caller
from screamingface_engine.rest.connections import _caller
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.runner.executor import BridgeOverflowError, Url4Executor, _Bridge
from screamingface_engine.trace_scope import (
    _node_span,
    bind_node_span,
    current_traceparent,
    run_trace_scope,
)
from screamingface_engine.world_config import ModelSpec
from url4.dag import run as url4_run
from url4.observe import NodeStarted
from url4.streaming.interfaces import TraceContext, Traced
from url4.streaming.protocol import SpanData


def _fake_request(headers: dict[str, str]) -> Request:
    """A real Starlette Request, so `_caller` is exercised through its actual signature."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/connections",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )


MODEL = "anthropic/claude-haiku-4-5"
IDENTITY = {"X-User-Email": "someone@openmined.org"}

TRACEPARENT = re.compile(r"^00-(?!0{32}$)([0-9a-f]{32})-(?!0{16}$)([0-9a-f]{16})-[0-9a-f]{2}$")
"""The same shape url4's own parser accepts, including its two all-zero rejections.

Restated rather than imported so a change to url4's regex that widened what counts as valid
would surface here as a failure rather than be adopted silently — this IS the contract the
gateway will parse.
"""

TRACE_A = TraceContext(trace_id="a" * 32, root_span_id="1" * 16)
TRACE_B = TraceContext(trace_id="b" * 32, root_span_id="2" * 16)


class _MockAigateway:
    """Records every request the connector makes, answering each with a minimal completion."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )


async def _run_in_scope(
    trace: TraceContext | None,
    *,
    identity: dict[str, str] | None = None,
    profile: str | None = None,
) -> httpx.Request:
    """One model call made inside `trace`'s scope; returns the request that reached aigateway."""
    gw = _MockAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(
            cfg, client=client, identity_headers=identity, profile=profile
        )
        with run_trace_scope(trace):
            await url4_run(f"/{MODEL}('ctx')!'go'", world.node)
    assert len(gw.requests) == 1
    return gw.requests[0]


# --- the scope itself -------------------------------------------------------------------------


def test_outside_any_run_there_is_no_traceparent() -> None:
    """The control plane must stay byte-identical — no header, not an empty or zero one."""
    assert current_traceparent() is None


def test_the_scope_renders_the_bound_runs_trace_as_a_w3c_traceparent() -> None:
    with run_trace_scope(TRACE_A):
        rendered = current_traceparent()

    assert rendered is not None
    match = TRACEPARENT.match(rendered)
    assert match, rendered
    assert match.group(1) == TRACE_A.trace_id


def test_the_scope_is_restored_on_exit() -> None:
    """Nested and sequential runs in one process must not leak into each other."""
    with run_trace_scope(TRACE_A):
        with run_trace_scope(TRACE_B):
            assert current_traceparent() is not None
            inner = current_traceparent()
        outer = current_traceparent()

    assert inner is not None and outer is not None
    assert TRACEPARENT.match(inner).group(1) == TRACE_B.trace_id  # type: ignore[union-attr]
    assert TRACEPARENT.match(outer).group(1) == TRACE_A.trace_id  # type: ignore[union-attr]
    assert current_traceparent() is None


def test_a_scope_bound_to_no_trace_renders_nothing() -> None:
    """`execute` is called with `trace=None` by callers that never resolved one."""
    with run_trace_scope(None):
        assert current_traceparent() is None


# --- the connector: the run's trace -> the chat-completions request ---------------------------


@pytest.mark.asyncio
async def test_the_connector_sends_the_runs_traceparent() -> None:
    request = await _run_in_scope(TRACE_A)

    sent = request.headers.get("traceparent")
    assert sent is not None, (
        "the engine sent no traceparent — this is the audit's finding, and the whole of rung 2"
    )
    match = TRACEPARENT.match(sent)
    assert match, sent
    assert match.group(1) == TRACE_A.trace_id, "the gateway got A trace id, not THIS run's"


@pytest.mark.asyncio
async def test_a_call_outside_any_run_sends_no_traceparent_header() -> None:
    """Absent is absent — never a well-formed header carrying an all-zero or invented id.

    A zero id would parse, join nothing, and look correct in every log it reached.
    """
    request = await _run_in_scope(None)

    assert "traceparent" not in request.headers


@pytest.mark.asyncio
async def test_the_gateway_owned_profile_still_wins_over_an_inbound_value() -> None:
    """The INVARIANT at `connector._headers` must survive gaining a third header.

    Envoy guarantees the identity header is not forged, but nothing guarantees the mapping
    reaching the connector holds ONLY that key.
    """
    request = await _run_in_scope(
        TRACE_A,
        identity={**IDENTITY, "X-Profile": "attacker-profile", "traceparent": "00-" + "f" * 32},
        profile="gateway-owned",
    )

    assert request.headers["x-profile"] == "gateway-owned"
    match = TRACEPARENT.match(request.headers["traceparent"])
    assert match, request.headers["traceparent"]
    assert match.group(1) == TRACE_A.trace_id, (
        "an inbound traceparent displaced the run's own — the header is gateway-owned and must "
        "be written last, exactly as X-Profile is"
    )


@pytest.mark.asyncio
async def test_identity_still_travels_alongside_the_traceparent() -> None:
    """Guards against the new key being written by replacing the identity mapping."""
    request = await _run_in_scope(TRACE_A, identity=IDENTITY)

    assert request.headers["X-User-Email"] == IDENTITY["X-User-Email"]
    assert "traceparent" in request.headers
    assert "authorization" not in request.headers


# --- the executor: where the scope comes from -------------------------------------------------


@pytest.mark.asyncio
async def test_execute_binds_the_trace_it_was_handed() -> None:
    """The id must come from `lifecycle.run`, which is the ONLY place both cases are known.

    `logs.RunContext.trace_id` is the tempting source and is wrong: `runner/main.py` binds
    `parse_traceparent(env)`, which is None when the caller sent none — and url4 then mints one
    that never reaches it. Reading that would propagate for client-originated runs (passing
    rung 2) and silently propagate nothing for the rest.
    """
    gw = _MockAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(world.node)
        async for _ in executor.execute(f"/{MODEL}('ctx')!'go'", trace=TRACE_A):
            pass

    assert gw.requests, "the run made no model call"
    match = TRACEPARENT.match(gw.requests[0].headers.get("traceparent", ""))
    assert match, gw.requests[0].headers.get("traceparent")
    assert match.group(1) == TRACE_A.trace_id


@pytest.mark.asyncio
async def test_two_runs_on_one_cached_world_do_not_share_a_trace_id() -> None:
    """The regression a constructor argument would cause, asserted directly.

    `Url4Executor._resolve_world` caches `self._io`, so `build_aigateway_world` runs once per
    executor while serve mode drives many runs through it. A per-run value parked on that
    shared object is one run reading another's — the defect `build_aigateway_world`'s own
    docstring warns about for `cache`.
    """
    gw = _MockAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(world.node)
        for trace in (TRACE_A, TRACE_B):
            async for _ in executor.execute(f"/{MODEL}('ctx')!'go'", trace=trace):
                pass

    assert len(gw.requests) == 2, "expected one model call per run"
    first, second = (r.headers.get("traceparent", "") for r in gw.requests)
    assert TRACEPARENT.match(first).group(1) == TRACE_A.trace_id  # type: ignore[union-attr]
    assert TRACEPARENT.match(second).group(1) == TRACE_B.trace_id, (  # type: ignore[union-attr]
        "the second run reused the first run's trace id — the world outlived the run that "
        "built it, which is exactly why the trace is a ContextVar and not a field"
    )


@pytest.mark.asyncio
async def test_a_run_with_no_inbound_traceparent_still_propagates_the_minted_id() -> None:
    """The hole `logs.RunContext` would leave, asserted as its own case.

    url4 mints a trace id when the caller sent none, and that run's model calls must carry it
    — otherwise the deployed no-inbound-traceparent path stays anonymous while the ladder,
    whose client always originates one, reports green.
    """
    minted = TraceContext(trace_id="c" * 32, root_span_id="3" * 16)
    gw = _MockAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(world.node)
        async for _ in executor.execute(f"/{MODEL}('ctx')!'go'", trace=minted):
            pass

    match = TRACEPARENT.match(gw.requests[0].headers.get("traceparent", ""))
    assert match, "a run whose caller sent no traceparent propagated nothing"
    assert match.group(1) == minted.trace_id


# --- the connections path: the inbound request's trace -> the upstream call -------------------


class _RecordingUpstream:
    """Keeps every connections request, answering each path with the shape it must parse.

    `list()` makes TWO upstream calls — `/v1/providers` then `/v1/oauth/connections` — and they
    decode differently. Answering both with one shape makes the adapter raise before the
    assertion is reached, which reads as a propagation failure and is not one.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json={"object": "list", "data": []})
        return httpx.Response(200, json={"connections": []})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )


async def _list_as(caller: Caller) -> httpx.Request:
    """Drive one `list()` and return the `/v1/providers` request — the path the issue names."""
    upstream = _RecordingUpstream()
    async with upstream.client() as client:
        await AigatewayConnections(client).list(caller)
    providers = [r for r in upstream.requests if r.url.path == "/v1/providers"]
    assert len(providers) == 1, [r.url.path for r in upstream.requests]
    # EVERY upstream call must carry it, not just the one asserted on — a per-path regression
    # would otherwise hide behind the one request this helper returns.
    assert len({r.headers.get("traceparent") for r in upstream.requests}) == 1
    return providers[0]


@pytest.mark.asyncio
async def test_the_connections_path_forwards_the_requests_traceparent() -> None:
    """`/v1/providers` went out with identity alone — no traceparent, and no X-Profile."""
    inbound = "00-" + "d" * 32 + "-" + "4" * 16 + "-01"

    request = await _list_as(Caller(IDENTITY, traceparent=inbound, profile="p1"))

    assert request.headers["traceparent"] == inbound
    assert request.headers["X-Profile"] == "p1"
    assert request.headers["X-User-Email"] == IDENTITY["X-User-Email"]


@pytest.mark.asyncio
async def test_a_connections_request_without_a_trace_sends_no_traceparent() -> None:
    request = await _list_as(Caller(IDENTITY))

    assert "traceparent" not in request.headers
    assert "x-profile" not in request.headers


@pytest.mark.asyncio
async def test_an_inbound_identity_mapping_cannot_displace_the_requests_own_trace() -> None:
    """Gateway-owned headers are written last here too — the same INVARIANT as the connector."""
    ours = "00-" + "e" * 32 + "-" + "5" * 16 + "-01"
    forged = {**IDENTITY, "traceparent": "00-" + "0" * 32 + "-" + "0" * 16 + "-01"}

    request = await _list_as(Caller(forged, traceparent=ours, profile="mine"))

    assert request.headers["traceparent"] == ours


def test_the_rest_edge_drops_a_malformed_inbound_traceparent() -> None:
    """Invalid degrades to ABSENT, never to an error and never forwarded as-is.

    Forwarding garbage would be rejected downstream or, worse, parsed into a trace that joins
    nothing. Failing the request instead would let a bad trace header break an otherwise valid
    connections call, which is a availability regression for a diagnostic feature.
    """
    request = _fake_request({"traceparent": "not-a-traceparent", "X-User-Email": "a@b.c"})

    caller = _caller(request)

    assert caller.traceparent is None
    assert caller.identity == {"X-User-Email": "a@b.c"}


def test_the_rest_edge_carries_a_valid_inbound_traceparent_through() -> None:
    inbound = "00-" + "9" * 32 + "-" + "8" * 16 + "-01"

    caller = _caller(_fake_request({"traceparent": inbound, "X-Profile": "prof"}))

    assert caller.traceparent == inbound
    assert caller.profile == "prof"


@pytest.mark.asyncio
async def test_a_cancelled_run_does_not_raise_from_the_trace_scope() -> None:
    """Regression: the scope must not hold a ContextVar token across an async-generator yield.

    `Url4Executor.execute` is an ASYNC GENERATOR, and consecutive steps of one can be driven
    from different contexts — `asyncio.ensure_future(gen.__anext__())` runs that step in a new
    Task with a COPIED context. A token set in one and reset in another raises
    `ValueError: Token was created in a different Context`.

    `test_runner_summary.py::test_a_cancelled_run_records_stopped` is what caught this, but its
    name promises nothing about contexts, so the constraint is restated here where a later
    change to `trace_scope` would look for it.
    """
    import asyncio

    from url4.io.static import StaticIOLayer

    gate = asyncio.Event()

    async def gated(_context: str, _intent: str) -> str:
        await gate.wait()
        return "GATED"

    io = StaticIOLayer(fetch_map={"https://fast": "FAST"}, routes={"/gated": gated})
    generator = Url4Executor(io).execute("(f=https://fast, g=/gated()!go)!'$f $g'", trace=TRACE_A)

    await asyncio.wait_for(generator.__anext__(), timeout=2.0)
    pending = asyncio.ensure_future(generator.__anext__())
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    # And the scope really is unbound afterwards — a leaked binding would attribute the NEXT
    # run's model calls to this cancelled one.
    assert current_traceparent() is None


# --- OME-1185: the CALLING NODE's span, not the run's root ------------------------------------
#
# `OME-1119` (above) bound `root_span_id`, because nothing emitted a root span yet and a
# per-node parent would have dangled. `OME-1130` made per-node spans real, so every aigateway
# server span hanging off the run's root is now merely FLAT: production trace
# e2f0bfb83234b51d0228ce0fa39c0334 (2026-09-17 04:25 UTC) held 200 spans — screamingface-engine
# 176 + aigateway 24, 1 root, 0 orphans — and all 24 gateway server spans shared the single
# parent c84b53aff1cdcb16, so no gateway call could be attributed to the node that made it.


def test_a_bound_node_span_is_what_the_traceparent_names() -> None:
    """The span segment is the CALLING NODE's, while the trace id stays the run's."""
    with run_trace_scope(TRACE_A):
        bind_node_span("7" * 16)
        rendered = current_traceparent()

    assert rendered is not None
    match = TRACEPARENT.match(rendered)
    assert match, rendered
    assert match.group(1) == TRACE_A.trace_id
    assert match.group(2) == "7" * 16, "the gateway was told the run's root, not the node"


def test_with_no_node_bound_the_scope_still_names_the_runs_root() -> None:
    """Outside a node the run's root IS the current span — `OME-1119`'s contract, unchanged."""
    with run_trace_scope(TRACE_A):
        rendered = current_traceparent()

    assert rendered is not None
    assert TRACEPARENT.match(rendered).group(2) == TRACE_A.root_span_id  # type: ignore[union-attr]


def test_a_nested_run_does_not_inherit_the_outer_runs_node_span() -> None:
    """A stale node id would attribute an inner run's calls to a node of the outer one."""
    with run_trace_scope(TRACE_A):
        bind_node_span("7" * 16)
        with run_trace_scope(TRACE_B):
            inner = current_traceparent()
        outer = current_traceparent()

    assert inner is not None and outer is not None
    assert TRACEPARENT.match(inner).group(2) == TRACE_B.root_span_id  # type: ignore[union-attr]
    assert TRACEPARENT.match(outer).group(2) == "7" * 16  # type: ignore[union-attr]


def test_a_node_span_bound_outside_any_run_sends_nothing() -> None:
    """Absent stays absent: a node id without a run is not a trace."""
    bind_node_span("7" * 16)

    assert current_traceparent() is None


@pytest.mark.asyncio
async def test_the_gateway_is_told_the_node_that_called_it_not_the_run_root() -> None:
    """The whole ticket, end to end: the parent id aigateway receives is a node the run
    actually exported a span for — never the synthetic root every call used to share.

    The exported span ids are walked off `Traced.span.span_id`. Asserting over a rendering of
    the frames instead (`repr`, `str`) is how a security test in this repo once passed against
    anything at all.
    """
    gw = _MockAigateway()
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    node_span_ids: set[str] = set()
    calling_span_ids: set[str] = set()
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(world.node)
        async for step in executor.execute(f"/{MODEL}('ctx')!'go'", trace=TRACE_A):
            if not isinstance(step, Traced) or step.span is None:
                continue
            node_span_ids.add(step.span.span_id)
            # The node that CALLED the gateway is the one whose span reports a request model:
            # `_RunState` fills that field from the usage the connector reported on this span.
            if isinstance(step.payload, SpanData) and step.payload.request_model is not None:
                calling_span_ids.add(step.span.span_id)

    assert gw.requests, "the run made no model call"
    assert len(calling_span_ids) == 1, f"expected one model-calling node, got {calling_span_ids}"
    sent = gw.requests[0].headers.get("traceparent", "")
    match = TRACEPARENT.match(sent)
    assert match, sent
    assert match.group(1) == TRACE_A.trace_id
    assert match.group(2) != TRACE_A.root_span_id, (
        "every gateway span still hangs off the run's root — this is the flatness OME-1185 fixes"
    )
    assert match.group(2) in node_span_ids, (
        "the gateway was given a span id the run never exported — a dangling parent renders as "
        f"a gap: sent {match.group(2)!r}, exported {sorted(node_span_ids)}"
    )
    assert match.group(2) == calling_span_ids.pop(), (
        "the gateway was parented to some OTHER node of the run — a plausible id that puts the "
        "call under the wrong node is worse than the flat trace it replaced"
    )


def test_a_node_start_the_bridge_cannot_buffer_still_binds_its_span() -> None:
    """The binding must not ride on the queueing policy.

    A `NodeStarted` the buffer refuses still describes a node that is about to call the
    gateway; if the bind sat after the overflow guard, that node's calls would silently fall
    back to the run's root — the exact flatness this ticket removes, restored only under load.
    """
    bridge = _Bridge(1, memory_budget=1)
    bridge.on_event(NodeStarted("a" * 16, None, "Node", ""))

    with run_trace_scope(TRACE_A):
        with pytest.raises(BridgeOverflowError):
            bridge.on_event(NodeStarted("b" * 16, "a" * 16, "Node", ""))
        rendered = current_traceparent()

    assert rendered is not None
    assert TRACEPARENT.match(rendered).group(2) == "b" * 16  # type: ignore[union-attr]


# --- OME-1185 follow-up: the per-Task isolation the whole design rests on -----------------------
#
# Review finding: every test above this line passes if `_node_span` is a plain module-level
# global instead of a ContextVar. The binding is set-and-never-reset precisely BECAUSE each
# node resolves in its own `asyncio.Task` (`url4.dag.executor.Executor._run` ->
# `tg.create_task(self._eval(...))`), so a sibling's binding cannot reach this node's outbound
# calls. Nothing pinned that, and it is the property a regression would break: under a global,
# a fan-out run attributes every concurrent node's gateway calls to whichever sibling bound
# last — a plausible-looking WRONG parent, which this ticket argues is worse than the flat
# trace it replaces.


@pytest.fixture(autouse=True)
def _reset_node_span_between_tests() -> Iterator[None]:
    """Module-wide: no test may leave a node span bound in the runner's root context.

    `test_a_node_span_bound_outside_any_run_sends_nothing` and
    `test_a_node_start_the_bridge_cannot_buffer_still_binds_its_span` both bind outside any
    scope, and `run_trace_scope` (which clears on entry) is the only thing that makes that
    harmless for the tests that follow. That is ordering as a load-bearing accident; this
    removes it.
    """
    yield
    _node_span.set(None)


@pytest.mark.asyncio
async def test_concurrent_siblings_each_render_their_own_node_span() -> None:
    """Two Tasks bind, THEN both read — the ordering a module-level global cannot survive.

    The barrier is what makes this deterministic rather than a race: every sibling has bound
    before any sibling reads, so a single shared slot necessarily hands both of them the id
    that was written last.
    """
    import asyncio

    span_ids = ("a" * 16, "b" * 16, "c" * 16)
    rendered: dict[str, str | None] = {}
    all_bound = asyncio.Barrier(len(span_ids))

    async def resolve_one_node(span_id: str) -> None:
        bind_node_span(span_id)
        await all_bound.wait()
        rendered[span_id] = current_traceparent()

    with run_trace_scope(TRACE_A):
        async with asyncio.TaskGroup() as group:
            for span_id in span_ids:
                group.create_task(resolve_one_node(span_id))
        # And the siblings' bindings never escaped into the parent context either.
        parent = current_traceparent()

    assert set(rendered) == set(span_ids)
    for span_id, value in rendered.items():
        assert value is not None, span_id
        match = TRACEPARENT.match(value)
        assert match, value
        assert match.group(1) == TRACE_A.trace_id
        assert match.group(2) == span_id, (
            f"node {span_id} rendered sibling span {match.group(2)!r} — the node binding is "
            "shared process state, not per-Task, so a fan-out run parents every gateway call "
            "to whichever node bound last"
        )
    assert parent is not None
    assert TRACEPARENT.match(parent).group(2) == TRACE_A.root_span_id  # type: ignore[union-attr]


SECOND_MODEL = "anthropic/claude-sonnet-4-5"
SINK_MODEL = "anthropic/claude-opus-4-1"
"""A THIRD model for the reducing node, so every node in the fan-out run calls a distinct one.

`(a=…, b=…)!'$a $b'` is three model calls, not two: the outer intent resolves against the
run's default model. Giving the sink its own id keeps `request_model` a unique key per node.
"""


@pytest.mark.asyncio
async def test_a_fan_out_run_parents_each_gateway_call_to_the_node_that_made_it() -> None:
    """The same claim through the real executor: two model-calling nodes, resolved concurrently.

    Correlation is by MODEL, which is the one thing both halves carry: the request body names
    the model the node called, and that node's exported `SpanData.request_model` names the same
    one. So `sent[model]` and `exported[model]` can be compared directly — no `repr()`, no
    positional guessing about which request belongs to which node.
    """
    gw = _MockAigateway()
    cfg = AigatewayConfig(
        models=(ModelSpec(id=MODEL), ModelSpec(id=SECOND_MODEL), ModelSpec(id=SINK_MODEL)),
        default_model=SINK_MODEL,
    )
    exported: dict[str, str] = {}
    node_span_ids: set[str] = set()
    expression = f"(a=/{MODEL}('ctx')!'go', b=/{SECOND_MODEL}('ctx')!'go')!'$a $b'"
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(world.node)
        async for step in executor.execute(expression, trace=TRACE_A):
            if not isinstance(step, Traced) or step.span is None:
                continue
            node_span_ids.add(step.span.span_id)
            if isinstance(step.payload, SpanData) and step.payload.request_model is not None:
                exported[step.payload.request_model] = step.span.span_id

    assert len(gw.requests) == 3, [r.url.path for r in gw.requests]
    sent: dict[str, str] = {}
    for request in gw.requests:
        match = TRACEPARENT.match(request.headers.get("traceparent", ""))
        assert match, request.headers.get("traceparent")
        assert match.group(1) == TRACE_A.trace_id
        sent[json.loads(request.content)["model"]] = match.group(2)

    assert set(sent) == {MODEL, SECOND_MODEL, SINK_MODEL}, sent
    concurrent = {sent[MODEL], sent[SECOND_MODEL]}
    assert len(concurrent) == 2, (
        f"both concurrent nodes sent the SAME parent span {sent} — one node's binding reached "
        "the other's call, which only happens if the binding is not per-Task"
    )
    assert TRACE_A.root_span_id not in set(sent.values())
    assert set(sent.values()) <= node_span_ids, (
        f"a gateway call named a span the run never exported: sent {sorted(set(sent.values()))}, "
        f"exported {sorted(node_span_ids)}"
    )
    assert sent == exported, (
        f"a gateway call was parented to the WRONG node: sent {sent}, exported {exported}"
    )


@pytest.mark.parametrize(
    "span_id",
    ["", "0" * 16, "7" * 15, "7" * 17, "G" * 16, "span-0", ("ab" * 8).upper()],
    ids=["empty", "all-zero", "too-short", "too-long", "not-hex", "synthetic", "upper-case"],
)
def test_a_node_span_that_is_not_a_span_id_sends_no_header_rather_than_the_root(
    span_id: str,
) -> None:
    """The silent-degradation hole: `_node_span.get() or trace.root_span_id`.

    `""` is falsy, so an unusable binding used to render the RUN's root — a well-formed,
    plausible, wrong parent, which is precisely the flat trace OME-1185 removes, restored
    silently in the one case (a bad id) where an operator most needs to be told. A node IS
    resolving here, so the root is not the current span and naming it is a lie; this module's
    standing answer for an id it cannot trust is to omit the header.

    The all-zero id is the same failure in W3C clothing — it parses everywhere and joins
    nothing — and `"span-0"` is the shape `test_url4_executor.py` feeds `_Bridge` directly.
    """
    with run_trace_scope(TRACE_A):
        bind_node_span(span_id)
        rendered = current_traceparent()

    assert rendered is None, (
        f"a node bound as {span_id!r} rendered {rendered!r} — an unusable node id must not be "
        "laundered into an attribution to the run's root, nor sent as a malformed header"
    )


def test_a_usable_node_span_bound_after_an_unusable_one_still_renders() -> None:
    """The screen is per-read, not a latch: rejecting one id must not disable the feature."""
    with run_trace_scope(TRACE_A):
        bind_node_span("")
        assert current_traceparent() is None
        bind_node_span("7" * 16)
        rendered = current_traceparent()

    assert rendered is not None
    assert TRACEPARENT.match(rendered).group(2) == "7" * 16  # type: ignore[union-attr]
