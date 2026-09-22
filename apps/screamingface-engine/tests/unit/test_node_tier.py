"""Unit 3 — the node tier: the sync surface, its identity isolation, and its ladder.

# WHY this file exists, and why T1 is first. The sync surface shares ONE world across every
# caller (F2), so a leaked ContextVar binding would let caller A's request leave on caller B's
# aigateway call — the single highest-impact defect this change can ship (`contracts.md` C3,
# test-plan.md R1). T1 drives two real concurrent requests through the real ASGI stack and a
# stubbed aigateway and asserts each outbound call carried its own caller state. Everything
# after it pins the ladder (T4), the dispatch edges (T9, T11, T12), readiness/offline start
# (T13), the 502 mapping (AC10), and the observability test-plan §9 requires.

# Stubbed aigateway throughout: no real external API is ever called, so the suite runs offline.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import tomllib
from collections.abc import Iterator

import httpx
import pytest
from test_aigateway_connector import _MockAigateway

import screamingface_engine.world.connector as connector_module
from screamingface_engine.logs import APP_LOGGER, configure, run_scope
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig, parse_config
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world.node_tier import (
    NodeReadiness,
    NodeTier,
    NodeTierSettings,
    build_node_metrics,
    build_node_tier,
)
from screamingface_engine.world.serving import MountCollisionError
from url4.peer.server import Url4Node
from url4.streaming.protocol.signals import ResultArtifact

_MODEL = "anthropic/claude-haiku-4-5"
_FAST = NodeTierSettings(request_timeout_s=5.0, aigateway_timeout_s=4.0)
_KEY = "node-tier-test-artifact-signing-key-0123456789"
_TRACE = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
_TRACE_ID = "a" * 32


@pytest.fixture(autouse=True)
def _fast_transport_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero the connector's transport backoff so a 502 test does not sleep 0.5 s + jitter."""
    monkeypatch.setattr(connector_module, "_TRANSPORT_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(connector_module, "_TRANSPORT_BACKOFF_JITTER_S", 0.0)


def _config(models: tuple[str, ...] = (_MODEL,)) -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=models[0],
            models=tuple(ModelSpec(id=model) for model in models),
        )
    )


class _NeverSpills:
    """A trusted, injected spill store for tests whose bodies stay far under the inline cap.

    WHY (FX-8/FX-9): `build_node_tier` refuses a filesystem store read from the env and an empty
    signing key, so a test that is not about spilling injects this store and `_KEY`.
    """

    def write_bytes(self, encoded: bytes) -> ResultArtifact:
        raise AssertionError("a small sync body must never spill")

    def write_text(self, body: str) -> ResultArtifact:
        raise AssertionError("a small sync body must never spill")


_NEVER_SPILLS = _NeverSpills()


def _node_client(tier: NodeTier) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=tier), base_url="http://node.test")


async def _serve(
    route_ids: tuple[str, ...] = (_MODEL,),
    settings: NodeTierSettings = _FAST,
    real_ids: tuple[str, ...] | None = None,
):
    """Build a started tier over a stubbed aigateway, plus the stub and its client.

    ``route_ids`` are the DECLARED (url4-route) ids; ``real_ids`` are the gateway ids the stub
    answers for. They differ only for a colon-bearing route (T11), where the world carries the
    ``~``-encoded form and aigateway sees the real id.
    """
    gw = _MockAigateway(real_ids if real_ids is not None else route_ids)
    client = gw.client()
    tier = await build_node_tier(
        env={},
        config=_config(route_ids),
        client=client,
        settings=settings,
        artifact_store=_NEVER_SPILLS,
        artifact_signing_key=_KEY,
    )
    return tier, gw, client


def _count(tier: NodeTier, name: str, labels: dict[str, str] | None = None) -> float | None:
    return tier.metrics.registry.get_sample_value(name, labels)


def test_the_ladder_numbers_live_in_settings_and_decrease_inward() -> None:
    """contracts.md: timeouts must decrease inward so the inner failure wins the race."""
    settings = NodeTierSettings()
    assert settings.request_timeout_s == 30.0
    assert settings.aigateway_timeout_s == 28.0
    assert settings.request_timeout_s > settings.aigateway_timeout_s
    assert settings.max_inflight == 2 * max(1, settings.workers)


def test_the_tier_overrides_allow_outbound_and_the_aigateway_timeout() -> None:
    """C3/§10: the tier must not inherit url4.toml's 600 s or its outbound allowance."""
    from screamingface_engine.world.node_tier import _tier_config

    overridden = _tier_config(_config(), NodeTierSettings())
    assert overridden.aigateway is not None
    assert overridden.aigateway.allow_outbound is False
    assert overridden.aigateway.timeout_s == 28.0


@pytest.mark.asyncio
async def test_a_started_tier_keeps_url4s_default_eval_path() -> None:
    """D3: the eval path stays `/v1`; wrapper routes never shadow it."""
    from screamingface_engine.world.serving import node_eval_path

    tier, _gw, client = await _serve()
    try:
        assert node_eval_path(tier._node) == "/v1"
    finally:
        await tier.aclose()
        await client.aclose()


# --- T1 / AC3: two concurrent sync callers never cross ---------------------------------------


@pytest.mark.asyncio
async def test_a_mount_call_returns_the_model_answer() -> None:
    """AC1: one direct mount hit returns the model's answer as text/plain."""
    gw = _MockAigateway((_MODEL,), responses={_MODEL: "PARIS"})
    async with gw.client() as client:
        tier = await build_node_tier(
            env={},
            config=_config(),
            client=client,
            settings=_FAST,
            artifact_store=_NEVER_SPILLS,
            artifact_signing_key=_KEY,
        )
        try:
            async with _node_client(tier) as node:
                response = await node.get(
                    f"/{_MODEL}",
                    params={"q": "('')!'Reply with exactly: PARIS'"},
                    headers={"X-User-Email": "a@x.test", "traceparent": _TRACE},
                )
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/plain; charset=utf-8"
            assert response.text == "PARIS"
            outbound = gw.posts_to(_MODEL)[0]
            assert outbound.headers["X-User-Email"] == "a@x.test"
            assert outbound.headers["traceparent"] == _TRACE
        finally:
            await tier.aclose()


@pytest.mark.asyncio
async def test_two_concurrent_sync_requests_keep_their_own_caller_state() -> None:
    """THE defining sync test (prd/03 T1, AC3).

    One world, one node, two concurrent mount calls bound to different scopes. A retained
    binding — the pre-F2 shape — would put one caller's identity, profile, seed and cache on
    the other's outbound call. Mapped by identity so the assertion cannot pass by accident of
    response ordering.
    """
    tier, gw, client = await _serve()
    try:
        async with _node_client(tier) as node:
            first, second = await asyncio.gather(
                node.get(
                    f"/{_MODEL}",
                    params={"q": "('')!'ctx-a'"},
                    headers={
                        "X-User-Email": "a@x.test",
                        "X-Profile": "profile-a",
                        "X-Answer-Seed": "11",
                        "Cache-Control": "no-store",
                        "traceparent": _TRACE,
                    },
                ),
                node.get(
                    f"/{_MODEL}",
                    params={"q": "('')!'ctx-b'"},
                    headers={
                        "X-User-Email": "b@x.test",
                        "X-Profile": "profile-b",
                        "X-Answer-Seed": "22",
                    },
                ),
            )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text

        by_identity = {r.headers["X-User-Email"]: r for r in gw.posts_to(_MODEL)}
        a, b = by_identity["a@x.test"], by_identity["b@x.test"]

        assert a.headers["X-Profile"] == "profile-a"
        assert b.headers["X-Profile"] == "profile-b"
        assert a.headers["traceparent"] == _TRACE
        assert "traceparent" not in b.headers

        body_a, body_b = json.loads(a.content), json.loads(b.content)
        assert body_a["seed"] == 11
        assert body_b["seed"] == 22
        assert body_a["cache"] == {"use-cache": False}
        assert "cache" not in body_b
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_a_request_without_a_verified_identity_is_still_scoped_not_anonymous() -> None:
    """The node tier forwards no identity when none arrived (D4 is enforced at the App)."""
    tier, gw, client = await _serve()
    try:
        async with _node_client(tier) as node:
            response = await node.get(f"/{_MODEL}", params={"q": "('')!'go'"})
        assert response.status_code == 200
        assert "X-User-Email" not in gw.posts_to(_MODEL)[0].headers
    finally:
        await tier.aclose()
        await client.aclose()


# --- T4 / AC6: the timeout returns 504, names the ensemble path, cancels downstream ----------


@pytest.mark.asyncio
async def test_a_slow_call_times_out_cleanly_and_cancels_the_gateway_call() -> None:
    """The cancellation clause is the point: an abandoned aigateway call still bills."""
    cancelled = asyncio.Event()

    async def hanging(request: httpx.Request) -> httpx.Response:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("unreachable")  # pragma: no cover

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(hanging), base_url="http://aigateway.test"
    )
    settings = NodeTierSettings(request_timeout_s=0.05, aigateway_timeout_s=0.04)
    tier = await build_node_tier(
        env={},
        config=_config(),
        client=client,
        settings=settings,
        artifact_store=_NEVER_SPILLS,
        artifact_signing_key=_KEY,
    )
    try:
        async with _node_client(tier) as node:
            response = await node.get(
                f"/{_MODEL}",
                params={"q": "('')!'go'"},
                headers={"X-User-Email": "a@x.test"},
            )
        assert response.status_code == 504
        body = response.json()["error"]
        assert body["code"] == "timeout"
        assert "ensemble" in body["message"], body["message"]
        # The 504 RATE signal is derivable from the duration histogram (test-plan §9 item 1).
        assert (
            _count(
                tier,
                "screamingface_engine_node_sync_request_duration_seconds_count",
                {"status": "504"},
            )
            == 1
        )
        # The in-flight httpx call observed the cancellation, not merely a severed client.
        await asyncio.wait_for(cancelled.wait(), timeout=1.0)
    finally:
        await tier.aclose()
        await client.aclose()


# --- T9 / AC11: a mount without `q` explains itself ------------------------------------------


@pytest.mark.asyncio
async def test_a_known_mount_without_q_returns_400_naming_q() -> None:
    """url4 would fall through to the data routes and 404 endpoint_not_found; we intercept."""
    tier, _gw, client = await _serve()
    try:
        async with _node_client(tier) as node:
            response = await node.get(f"/{_MODEL}")
        assert response.status_code == 400
        body = response.json()["error"]
        assert body["code"] == "missing_intent"
        assert "q" in body["message"]
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_an_unknown_path_still_404s_at_the_node() -> None:
    """The missing-q intercept is scoped to KNOWN mounts — a typo must keep url4's 404."""
    tier, _gw, client = await _serve()
    try:
        async with _node_client(tier) as node:
            response = await node.get("/nope/not-a-mount")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "endpoint_not_found"
    finally:
        await tier.aclose()
        await client.aclose()


# --- T11 / AC13: a colon-bearing id resolves in its tilde-encoded form -----------------------


@pytest.mark.asyncio
async def test_a_colon_bearing_model_id_is_addressable_via_the_tilde_route() -> None:
    route_id = "huggingface/org/model~novita"
    real_id = "huggingface/org/model:novita"
    tier, gw, client = await _serve((route_id,), real_ids=(real_id,))
    # The declared world carries the ENCODED route form (OME-873): the config above builds the
    # node with `/huggingface/org/model~novita`, which is the path a caller must write.
    try:
        async with _node_client(tier) as node:
            response = await node.get(
                f"/{route_id}",
                params={"q": "('')!'go'"},
                headers={"X-User-Email": "a@x.test"},
            )
        assert response.status_code == 200, response.text
        assert gw.posts_to(real_id), "the decoded real id never reached aigateway"
    finally:
        await tier.aclose()
        await client.aclose()


# --- T12 / AC14: non-GET is rejected per url4 GET-only doctrine ------------------------------


@pytest.mark.asyncio
async def test_a_non_get_method_on_a_mount_returns_405() -> None:
    tier, _gw, client = await _serve()
    try:
        async with _node_client(tier) as node:
            response = await node.post(f"/{_MODEL}", headers={"X-User-Email": "a@x.test"})
        assert response.status_code == 405
        assert response.json()["error"]["code"] == "method_not_allowed"
    finally:
        await tier.aclose()
        await client.aclose()


# --- AC7: over capacity sheds with 503 + Retry-After -----------------------------------------


@pytest.mark.asyncio
async def test_the_in_flight_cap_sheds_with_503_and_retry_after() -> None:
    entered = asyncio.Event()

    async def hanging(request: httpx.Request) -> httpx.Response:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(hanging), base_url="http://aigateway.test"
    )
    settings = NodeTierSettings(
        request_timeout_s=5.0, aigateway_timeout_s=4.0, max_inflight_per_worker=1, workers=1
    )
    tier = await build_node_tier(
        env={},
        config=_config(),
        client=client,
        settings=settings,
        artifact_store=_NEVER_SPILLS,
        artifact_signing_key=_KEY,
    )
    try:
        async with _node_client(tier) as node:
            first = asyncio.create_task(
                node.get(
                    f"/{_MODEL}", params={"q": "('')!'one'"}, headers={"X-User-Email": "a@x.test"}
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=1.0)
            second = await node.get(
                f"/{_MODEL}", params={"q": "('')!'two'"}, headers={"X-User-Email": "b@x.test"}
            )
            assert second.status_code == 503
            assert second.headers["retry-after"] == "1"
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        assert _count(tier, "screamingface_engine_node_sync_shed_total") == 1
    finally:
        await tier.aclose()
        await client.aclose()


# --- T13 / AC18: readiness gates on the world AND the collision guard ------------------------


@pytest.mark.asyncio
async def test_readiness_reports_503_until_the_world_is_ready() -> None:
    async def _never_called(scope: object, receive: object, send: object) -> None:
        raise AssertionError("/readyz never reaches the node")  # pragma: no cover

    tier = NodeTier(
        settings=NodeTierSettings(),
        metrics=build_node_metrics(),
        readiness=NodeReadiness(),
        node=Url4Node("readiness-test"),
        inner=_never_called,
        mounts=frozenset(),
        world_aclose=None,
    )
    async with _node_client(tier) as node:
        not_ready = await node.get("/readyz")
        assert not_ready.status_code == 503
        assert not_ready.json()["status"] == "not_ready"
        tier.readiness.succeed()
        ready = await node.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_a_failed_collision_guard_marks_readiness_failed_and_refuses_to_start() -> None:
    """The guard is passed the wrapper's own ops paths, so a mount at one fails startup (F4)."""
    config = parse_config(
        tomllib.loads('[data]\n"/token" = { value = "shadowed" }\n'),
        {},
        registry=EMPTY_MODEL_WORLD,
    )
    readiness = NodeReadiness()
    with pytest.raises(MountCollisionError):
        await build_node_tier(env={}, config=config, engine_routes={"/token"}, readiness=readiness)
    assert readiness.ready is False
    assert readiness.reason is not None and "/token" in readiness.reason


@pytest.mark.asyncio
async def test_a_started_tier_reports_ready() -> None:
    tier, _gw, client = await _serve()
    try:
        async with _node_client(tier) as node:
            assert (await node.get("/readyz")).status_code == 200
            assert (await node.get("/healthz")).status_code == 200
    finally:
        await tier.aclose()
        await client.aclose()


# --- T13 / AC19 and AC10: the build does no I/O; transport failures are 502 ------------------


class _UnreachableTransport(httpx.AsyncBaseTransport):
    """An aigateway that refuses every connection, counting attempts."""

    def __init__(self) -> None:
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise httpx.ConnectError("aigateway unreachable", request=request)


@pytest.mark.asyncio
async def test_the_world_builds_offline_and_calls_fail_502() -> None:
    """AC19: a tier that cannot start without its downstream turns one outage into two."""
    transport = _UnreachableTransport()
    client = httpx.AsyncClient(transport=transport, base_url="http://aigateway.test")
    tier = await build_node_tier(
        env={},
        config=_config(),
        client=client,
        settings=_FAST,
        artifact_store=_NEVER_SPILLS,
        artifact_signing_key=_KEY,
    )
    try:
        assert transport.calls == 0, "the world build must not touch the network"
        assert tier.readiness.ready is True
        async with _node_client(tier) as node:
            response = await node.get(
                f"/{_MODEL}",
                params={"q": "('')!'go'"},
                headers={"X-User-Email": "a@x.test"},
            )
        assert response.status_code == 502
        body = response.json()["error"]
        assert body["code"] == "aigateway_transport_error"
        assert transport.calls >= 1
    finally:
        await tier.aclose()
        await client.aclose()


# --- observability (test-plan §9) ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_sync_surface_records_duration_and_inflight() -> None:
    tier, _gw, client = await _serve()
    try:
        async with _node_client(tier) as node:
            response = await node.get(
                f"/{_MODEL}", params={"q": "('')!'go'"}, headers={"X-User-Email": "a@x.test"}
            )
        assert response.status_code == 200
        assert (
            _count(
                tier,
                "screamingface_engine_node_sync_request_duration_seconds_count",
                {"status": "200"},
            )
            == 1
        )
        assert _count(tier, "screamingface_engine_node_sync_inflight") == 0
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.fixture
def _restore_app_logger() -> Iterator[None]:
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
async def test_sync_request_logs_carry_origin_sync_and_the_trace_id(
    _restore_app_logger: None,
) -> None:
    """test-plan §9 item 3: without `origin`, sync and ensemble lines are indistinguishable."""
    stream = io.StringIO()
    configure(stream)
    tier, _gw, client = await _serve()
    try:
        async with _node_client(tier) as node:
            await node.get(
                f"/{_MODEL}",
                params={"q": "('')!'go'"},
                headers={"X-User-Email": "a@x.test", "traceparent": _TRACE},
            )
    finally:
        await tier.aclose()
        await client.aclose()

    rendered = stream.getvalue()
    assert "origin=sync" in rendered
    assert f"trace_id={_TRACE_ID}" in rendered
    assert "sync request mount=/" in rendered


def test_a_run_scope_line_still_carries_origin_run_topic_and_trace_id(
    _restore_app_logger: None,
) -> None:
    stream = io.StringIO()
    configure(stream)
    with run_scope("cap-topic", _TRACE_ID):
        logging.getLogger("screamingface_engine.ws.bridge").info("run started")

    rendered = stream.getvalue()
    assert "origin=run topic=cap-topic" in rendered
    assert f"trace_id={_TRACE_ID}" in rendered


def test_node_mode_dispatches_to_the_node_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from screamingface_engine import cli

    called: list[str] = []
    monkeypatch.setattr(cli, "_node", lambda: called.append("node"))
    cli.main(["node"])
    assert called == ["node"]


def test_node_resolves_the_real_node_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_node` itself, unshimmed — so the lazy import is proven to resolve.

    The dispatch test above replaces `cli._node` wholesale and would keep passing if its import
    named a module that no longer existed. Patching the far side makes a rename in the node tier
    fail here rather than at a pod's first boot.
    """
    from screamingface_engine import cli
    from screamingface_engine.world import node_tier

    called: list[bool] = []
    monkeypatch.setattr(node_tier, "serve", lambda: called.append(True))

    cli._node()

    assert called == [True]
