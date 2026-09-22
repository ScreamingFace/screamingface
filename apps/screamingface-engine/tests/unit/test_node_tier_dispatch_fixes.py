"""Fix round B1 (04-review-fixes.md) — the node tier's request path after url4 returns.

FEATURE (unit 3, prd/03): the sync surface. These tests pin the fixes to the request path: the
deadline that bounds the aigateway retry (FX-1), the finish that runs outside url4's timeout
(FX-2), the 500 → 502 remap (FX-3), drain-only readiness (FX-4), `/metrics` off the mount port
(FX-5), the scoped log line (FX-6), the bucket range (FX-7), the overload `Retry-After`
(FX-12), one-phase construction (FX-15), the seed refusal code (FX-17) and a provable
overlap of two callers (FX-20).

Stubbed aigateway throughout: no real external API is called, so the suite runs offline.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from collections.abc import MutableMapping
from typing import Any

import httpx
import pytest
from test_aigateway_connector import _MockAigateway
from test_node_tier import _KEY, _NEVER_SPILLS, _config, _node_client

import screamingface_engine.world.connector as connector_module
from screamingface_engine.logs import APP_LOGGER, configure
from screamingface_engine.request_scope import current_scope
from screamingface_engine.world.node_tier import (
    NodeReadiness,
    NodeTier,
    NodeTierSettings,
    build_node_metrics,
    build_node_tier,
)
from url4.peer.server import Url4Node

_MODEL = "anthropic/claude-haiku-4-5"
_FAST = NodeTierSettings(request_timeout_s=5.0, aigateway_timeout_s=4.0)
_TRACE = "00-" + "c" * 32 + "-" + "d" * 16 + "-01"
_TRACE_ID = "c" * 32
_Q = {"q": "('')!'go'"}
_ME = {"X-User-Email": "a@x.test"}


async def _build(client: httpx.AsyncClient, settings: NodeTierSettings = _FAST) -> NodeTier:
    return await build_node_tier(
        env={},
        config=_config(),
        client=client,
        settings=settings,
        artifact_store=_NEVER_SPILLS,
        artifact_signing_key=_KEY,
    )


def _direct_tier(inner: Any, settings: NodeTierSettings = _FAST) -> NodeTier:
    """A tier over a hand-written inner app — the one-phase constructor (FX-15) as a seam."""
    readiness = NodeReadiness()
    readiness.succeed()
    return NodeTier(
        settings=settings,
        metrics=build_node_metrics(),
        readiness=readiness,
        node=Url4Node("dispatch-fixes"),
        inner=inner,
        mounts=frozenset(),
        world_aclose=None,
    )


def _answering(status: int, payload: dict[str, Any]) -> Any:
    async def inner(scope: Any, receive: Any, send: Any) -> None:
        body = json.dumps(payload).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return inner


# --- FX-1: the request deadline blocks a retry that cannot finish in time ---------------------


@pytest.mark.asyncio
async def test_a_retry_that_cannot_fit_the_deadline_is_not_started_and_the_caller_gets_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NT-H1: a second attempt the wrapper would cut off is billed and useless.

    The stub times out once, then hangs. Before FX-1 the connector slept and retried, the
    retry hung, and url4's wrapper answered 504. With the deadline in the scope there is no
    room for backoff + one attempt, so the connector gives up at once: 502, one POST.
    """
    monkeypatch.setattr(connector_module, "_TRANSPORT_BACKOFF_BASE_S", 0.3)
    monkeypatch.setattr(connector_module, "_TRANSPORT_BACKOFF_JITTER_S", 0.0)
    posts: list[httpx.Request] = []

    async def flaky_then_hanging(request: httpx.Request) -> httpx.Response:
        posts.append(request)
        if len(posts) == 1:
            raise httpx.ReadTimeout("synthetic read timeout", request=request)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(flaky_then_hanging),
        base_url="http://aigateway.test",
        timeout=0.3,
    )
    settings = NodeTierSettings(request_timeout_s=0.5, aigateway_timeout_s=0.3)
    tier = await _build(client, settings)
    try:
        async with _node_client(tier) as node:
            response = await node.get(f"/{_MODEL}", params=_Q, headers=_ME)
        assert response.status_code == 502, response.text
        assert response.json()["error"]["code"] == "aigateway_transport_error"
        assert len(posts) == 1
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_the_tier_binds_a_deadline_of_now_plus_the_request_budget() -> None:
    seen: list[float | None] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.append(current_scope().deadline)
        await _answering(200, {"ok": True})(scope, receive, send)

    tier = _direct_tier(inner)
    before = time.monotonic()
    async with _node_client(tier) as node:
        await node.get("/anything", headers=_ME)
    after = time.monotonic()
    deadline = seen[0]
    assert deadline is not None
    assert before + _FAST.request_timeout_s <= deadline <= after + _FAST.request_timeout_s


# --- FX-3: a downstream 500 is a 502; a url4 500 stays 500 ------------------------------------


@pytest.mark.asyncio
async def test_an_aigateway_401_answers_502_at_the_tier_with_its_code_kept() -> None:
    """NT-H3: url4 maps a permanent ResolutionError to 500; on a direct hit it is downstream."""
    gw = _MockAigateway((_MODEL,), responses={_MODEL: (401, {"message": "bad key"})})
    client = gw.client()
    tier = await _build(client)
    try:
        async with _node_client(tier) as node:
            response = await node.get(f"/{_MODEL}", params=_Q, headers=_ME)
        assert response.status_code == 502, response.text
        assert response.json()["error"]["code"] == "aigateway_http_401"
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_a_500_with_a_url4_error_code_stays_500() -> None:
    envelope = {"error": {"code": "internal_error", "message": "node bug"}}
    tier = _direct_tier(_answering(500, envelope))
    async with _node_client(tier) as node:
        response = await node.get("/anything", headers=_ME)
    assert response.status_code == 500
    assert response.json() == envelope


@pytest.mark.asyncio
async def test_a_500_with_a_downstream_code_becomes_502_and_keeps_code_and_message() -> None:
    envelope = {"error": {"code": "provider_refused", "message": "upstream said no"}}
    tier = _direct_tier(_answering(500, envelope))
    async with _node_client(tier) as node:
        response = await node.get("/anything", headers=_ME)
    assert response.status_code == 502
    assert response.json() == envelope


@pytest.mark.asyncio
async def test_an_inner_app_that_sends_nothing_still_gets_a_500_envelope() -> None:
    async def silent(scope: Any, receive: Any, send: Any) -> None:
        return None

    tier = _direct_tier(silent)
    async with _node_client(tier) as node:
        response = await node.get("/anything", headers=_ME)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


# --- FX-12: url4's overload 503 carries the tier's Retry-After --------------------------------


@pytest.mark.asyncio
async def test_the_overload_503_carries_the_configured_retry_after() -> None:
    entered = asyncio.Event()

    async def hanging(request: httpx.Request) -> httpx.Response:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(hanging), base_url="http://aigateway.test"
    )
    settings = NodeTierSettings(
        request_timeout_s=5.0, aigateway_timeout_s=4.0, max_inflight_per_worker=1, retry_after_s=7
    )
    tier = await _build(client, settings)
    try:
        async with _node_client(tier) as node:
            first = asyncio.create_task(node.get(f"/{_MODEL}", params=_Q, headers=_ME))
            await asyncio.wait_for(entered.wait(), timeout=1.0)
            second = await node.get(f"/{_MODEL}", params=_Q, headers=_ME)
            # FX-4 (RD2): saturation sheds with 503; it does NOT take the pod out of rotation.
            ready = await node.get("/readyz")
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        assert second.status_code == 503
        assert second.json()["error"]["code"] == "overloaded"
        assert second.headers["retry-after"] == "7"
        assert ready.status_code == 200
    finally:
        await tier.aclose()
        await client.aclose()


# --- FX-4: readiness is drain-only ------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_shutdown_drains_readiness_to_503() -> None:
    tier = _direct_tier(_answering(200, {"ok": True}))
    sent: list[MutableMapping[str, Any]] = []
    messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    async def receive() -> MutableMapping[str, Any]:
        return next(messages)

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    await tier({"type": "lifespan"}, receive, send)
    assert [m["type"] for m in sent] == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
    async with _node_client(tier) as node:
        ready = await node.get("/readyz")
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready", "reason": "draining"}


def test_drain_marks_readiness_not_ready_with_reason_draining() -> None:
    readiness = NodeReadiness()
    readiness.succeed()
    readiness.drain()
    assert readiness.ready is False
    assert readiness.reason == "draining"


# --- FX-5: /metrics is not served on the mount port -------------------------------------------


@pytest.mark.asyncio
async def test_metrics_is_not_served_on_the_mount_port() -> None:
    gw = _MockAigateway((_MODEL,))
    client = gw.client()
    tier = await _build(client)
    try:
        async with _node_client(tier) as node:
            response = await node.get("/metrics")
            health = await node.get("/healthz")
        # The path reaches the node like any other path; url4 answers its own 404.
        assert response.status_code == 404
        assert "screamingface_engine_node" not in response.text
        assert health.status_code == 200
    finally:
        await tier.aclose()
        await client.aclose()


# --- FX-6 / FX-7: the log line and the histogram ----------------------------------------------


@pytest.fixture
def _restore_app_logger() -> Any:
    logger = logging.getLogger(APP_LOGGER)
    handlers = list(logger.handlers)
    level, propagate = logger.level, logger.propagate
    logger.handlers.clear()
    try:
        yield
    finally:
        logger.handlers.clear()
        logger.handlers.extend(handlers)
        logger.setLevel(level)
        logger.propagate = propagate


@pytest.mark.asyncio
async def test_the_sync_request_line_itself_carries_origin_sync_and_the_trace_id(
    _restore_app_logger: None,
) -> None:
    """NT-M2: other lines carried the context; the per-request line did not."""
    stream = io.StringIO()
    configure(stream)
    tier = _direct_tier(_answering(200, {"ok": True}))
    async with _node_client(tier) as node:
        await node.get("/some-mount", headers={**_ME, "traceparent": _TRACE})
    lines = [line for line in stream.getvalue().splitlines() if "sync request mount=" in line]
    assert len(lines) == 1, stream.getvalue()
    assert "origin=sync" in lines[0]
    assert f"trace_id={_TRACE_ID}" in lines[0]
    assert "mount=/some-mount status=200" in lines[0]


@pytest.mark.asyncio
async def test_the_duration_histogram_has_buckets_past_the_request_budget() -> None:
    """NT-M3: the default buckets stop at 10 s, so every 30 s timeout fell in `+Inf`."""
    tier = _direct_tier(_answering(200, {"ok": True}))
    async with _node_client(tier) as node:
        await node.get("/anything", headers=_ME)
    name = "screamingface_engine_node_sync_request_duration_seconds_bucket"
    for le in ("30.0", "35.0", "40.0"):
        sample = tier.metrics.registry.get_sample_value(name, {"status": "200", "le": le})
        assert sample == 1, le


# --- FX-15 / FX-17 -----------------------------------------------------------------------------


def test_a_built_tier_exposes_its_mounts_publicly() -> None:
    tier = _direct_tier(_answering(200, {}))
    assert tier.mounts == frozenset()


@pytest.mark.asyncio
async def test_a_bad_answer_seed_is_400_malformed_header() -> None:
    tier = _direct_tier(_answering(200, {"ok": True}))
    async with _node_client(tier) as node:
        response = await node.get("/anything", headers={**_ME, "X-Answer-Seed": "eleven"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_header"
    assert "X-Answer-Seed" in response.json()["error"]["message"]


# --- FX-20: two callers provably in flight together --------------------------------------------


@pytest.mark.asyncio
async def test_two_overlapping_sync_requests_each_carry_their_own_identity() -> None:
    """NT-M8: T1 could pass with the two requests served one after the other.

    The stub holds each aigateway call on a two-party barrier, so neither answers until BOTH
    are in flight at once. A serialized tier would time out on the barrier instead.
    """
    barrier = asyncio.Barrier(2)
    seen: list[str] = []

    async def overlapping(request: httpx.Request) -> httpx.Response:
        async with asyncio.timeout(2.0):
            await barrier.wait()
        caller = request.headers["X-User-Email"]
        seen.append(caller)
        # The answer names the identity the OUTBOUND call carried, so each caller's response
        # proves which identity left on its own aigateway call.
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": f"for {caller}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(overlapping), base_url="http://aigateway.test"
    )
    tier = await _build(client)
    try:
        async with _node_client(tier) as node:
            first, second = await asyncio.gather(
                node.get(
                    f"/{_MODEL}", params={"q": "('')!'ctx-a'"}, headers={"X-User-Email": "a@x.t"}
                ),
                node.get(
                    f"/{_MODEL}", params={"q": "('')!'ctx-b'"}, headers={"X-User-Email": "b@x.t"}
                ),
            )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert sorted(seen) == ["a@x.t", "b@x.t"]
        assert first.text == "for a@x.t"
        assert second.text == "for b@x.t"
    finally:
        await tier.aclose()
        await client.aclose()
