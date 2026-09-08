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

import re

import httpx
import pytest
from starlette.requests import Request

from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import Caller
from screamingface_engine.rest.connections import _caller
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.trace_scope import current_traceparent, run_trace_scope
from screamingface_engine.world_config import ModelSpec
from url4.dag import run as url4_run
from url4.streaming.interfaces import TraceContext


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
