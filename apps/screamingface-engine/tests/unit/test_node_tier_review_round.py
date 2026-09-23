"""Fix round B1, review round (04-review-fixes.md §2.2a, §2.2b, FX-13) — the node tier.

FEATURE (unit 3, prd/03): the sync surface. These tests pin the review-round fixes: the tier's
own admission that covers the spill phase (§2.2a), the budget-exhausted counter (§2.2b), the
inverted caps that are no longer refused (FX-13), the store/key checks that run before the world
is built, and the one histogram sample per request with its FINAL status.

Stubbed aigateway throughout: no real external API is called, so the suite runs offline.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import tomllib
from typing import Any

import httpx
import pytest
from test_aigateway_connector import _MockAigateway
from test_node_tier import _KEY, _NEVER_SPILLS, _config, _node_client

import screamingface_engine.world.connector as connector_module
from screamingface_engine.world import node_tier
from screamingface_engine.world.config import parse_config
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world.node_tier import (
    NodeReadiness,
    NodeTier,
    NodeTierError,
    NodeTierSettings,
    build_node_metrics,
    build_node_tier,
)
from url4.peer.server import Url4Node
from url4.streaming.protocol.signals import ResultArtifact

_MODEL = "anthropic/claude-haiku-4-5"
_Q = {"q": "('')!'go'"}
_ME = {"X-User-Email": "a@x.test"}
_DURATION = "screamingface_engine_node_sync_request_duration_seconds"
_BUDGET = "screamingface_engine_node_sync_budget_exhausted_total"


class _CountingSlowStore:
    """A spill store that records how many writes run at once, each held ``seconds``."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._lock = threading.Lock()
        self.release = threading.Event()
        self.entered = threading.Event()
        self.active = 0
        self.max_active = 0
        self.writes = 0

    def write_bytes(self, encoded: bytes) -> ResultArtifact:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.entered.set()
        try:
            self.release.wait(self._seconds)
        finally:
            with self._lock:
                self.active -= 1
                self.writes += 1
        digest = hashlib.sha256(encoded).hexdigest()
        return ResultArtifact(id=digest, size_bytes=len(encoded), sha256=digest)

    def write_text(self, body: str) -> ResultArtifact:  # pragma: no cover - port completeness
        return self.write_bytes(body.encode())


def _sample(tier: NodeTier, name: str, labels: dict[str, str] | None = None) -> float | None:
    return tier.metrics.registry.get_sample_value(name, labels)


def _duration_samples(tier: NodeTier) -> dict[str, float]:
    """Every `status` label of the duration histogram with its observation count."""
    counts: dict[str, float] = {}
    for metric in tier.metrics.registry.collect():
        for sample in metric.samples:
            if sample.name == f"{_DURATION}_count":
                counts[sample.labels["status"]] = sample.value
    return counts


def _direct_tier(inner: Any, *, store: Any = None, **settings: Any) -> NodeTier:
    """A tier over a hand-written inner app, built with the one-phase constructor."""
    readiness = NodeReadiness()
    readiness.succeed()
    base: dict[str, Any] = {"request_timeout_s": 5.0, "aigateway_timeout_s": 4.0}
    return NodeTier(
        settings=NodeTierSettings(**{**base, **settings}),
        metrics=build_node_metrics(),
        readiness=readiness,
        node=Url4Node("review-round"),
        inner=inner,
        mounts=frozenset(),
        world_aclose=None,
        artifact_store=store,
        signing_key=_KEY,
    )


# --- §2.2a: the tier's admission covers the spill phase ---------------------------------------


async def _one_slot_spilling_tier(client: httpx.AsyncClient, store: Any) -> NodeTier:
    """A built tier with ONE in-flight slot, whose every answer spills (inline cap 10 bytes)."""
    return await build_node_tier(
        env={},
        config=_config(),
        client=client,
        settings=NodeTierSettings(
            request_timeout_s=5.0,
            aigateway_timeout_s=4.0,
            spill_timeout_s=2.0,
            max_inflight_per_worker=1,
            retry_after_s=7,
            result_inline_cap_bytes=10,
            result_hard_cap_bytes=1000,
        ),
        artifact_store=store,
        artifact_signing_key=_KEY,
    )


def _assert_shed_by_the_tier(*responses: httpx.Response) -> None:
    for shed in responses:
        assert shed.status_code == 503, shed.text
        assert shed.json()["error"]["code"] == "overloaded"
        assert shed.headers["retry-after"] == "7"


@pytest.mark.asyncio
async def test_a_spilling_request_still_holds_its_admission_slot() -> None:
    """The reviewer's probe: url4 frees its slot when `inner` returns, before the spill.

    With `max_inflight=1` and a 0.5 s spill, a second and a third request used to pass url4's
    gate and spill at the same time as the first. The tier's own counter holds the slot until
    `finish()` returns, so they are shed with url4's own `503 overloaded` envelope.
    """
    client = _MockAigateway((_MODEL,), responses={_MODEL: "B" * 64}).client()
    store = _CountingSlowStore(0.5)
    tier = await _one_slot_spilling_tier(client, store)
    try:
        async with _node_client(tier) as node:
            first = asyncio.create_task(node.get(f"/{_MODEL}", params=_Q, headers=_ME))
            assert await asyncio.to_thread(store.entered.wait, 2.0), "the first spill never began"
            # The first request is now past url4 and inside its spill.
            spilling_gauge = _sample(tier, "screamingface_engine_node_sync_inflight")
            second = await node.get(f"/{_MODEL}", params=_Q, headers=_ME)
            third = await node.get(f"/{_MODEL}", params=_Q, headers=_ME)
            store.release.set()
            first_response = await first
        assert first_response.status_code == 303, first_response.text
        _assert_shed_by_the_tier(second, third)
        assert store.max_active == 1
        assert store.writes == 1
        assert spilling_gauge == 1
        assert _sample(tier, "screamingface_engine_node_sync_shed_total") == 2
        assert _sample(tier, "screamingface_engine_node_sync_inflight") == 0
    finally:
        store.release.set()
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_a_shed_request_never_reaches_the_inner_app() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        calls.append(str(scope["path"]))
        entered.set()
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    tier = _direct_tier(inner, max_inflight_per_worker=1)
    async with _node_client(tier) as node:
        first = asyncio.create_task(node.get("/one", headers=_ME))
        await asyncio.wait_for(entered.wait(), timeout=1.0)
        try:
            # Bounded: without the tier's own gate this request reaches `inner` and waits.
            shed = await asyncio.wait_for(node.get("/two", headers=_ME), timeout=1.0)
        finally:
            release.set()
        assert (await first).status_code == 200
    assert shed.status_code == 503
    assert shed.json()["error"]["code"] == "overloaded"
    assert calls == ["/one"]


@pytest.mark.asyncio
async def test_a_non_overload_503_is_not_counted_as_shed() -> None:
    async def unavailable(scope: Any, receive: Any, send: Any) -> None:
        body = b'{"error": {"code": "provider_unavailable", "message": "down"}}'
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": body})

    tier = _direct_tier(unavailable)
    async with _node_client(tier) as node:
        response = await node.get("/anything", headers=_ME)
    assert response.status_code == 503
    assert _sample(tier, "screamingface_engine_node_sync_shed_total") == 0


# --- §2.2b: a budget that runs out upstream is counted ----------------------------------------


@pytest.mark.asyncio
async def test_a_retry_skipped_at_the_deadline_is_502_deadline_exceeded_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connector_module, "_TRANSPORT_BACKOFF_BASE_S", 0.3)
    monkeypatch.setattr(connector_module, "_TRANSPORT_BACKOFF_JITTER_S", 0.0)
    posts: list[httpx.Request] = []

    async def slow_then_hanging(request: httpx.Request) -> httpx.Response:
        posts.append(request)
        if len(posts) == 1:
            raise httpx.ReadTimeout("synthetic read timeout", request=request)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(slow_then_hanging),
        base_url="http://aigateway.test",
        timeout=0.3,
    )
    tier = await build_node_tier(
        env={},
        config=_config(),
        client=client,
        settings=NodeTierSettings(request_timeout_s=0.5, aigateway_timeout_s=0.3),
        artifact_store=_NEVER_SPILLS,
        artifact_signing_key=_KEY,
    )
    try:
        async with _node_client(tier) as node:
            response = await node.get(f"/{_MODEL}", params=_Q, headers=_ME)
        assert response.status_code == 502, response.text
        assert response.json()["error"]["code"] == "aigateway_deadline_exceeded"
        assert len(posts) == 1
        assert _sample(tier, _BUDGET) == 1
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_a_504_timeout_is_counted_as_budget_exhausted() -> None:
    async def hanging(request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(hanging), base_url="http://aigateway.test"
    )
    tier = await build_node_tier(
        env={},
        config=_config(),
        client=client,
        settings=NodeTierSettings(request_timeout_s=0.05, aigateway_timeout_s=0.04),
        artifact_store=_NEVER_SPILLS,
        artifact_signing_key=_KEY,
    )
    try:
        async with _node_client(tier) as node:
            response = await node.get(f"/{_MODEL}", params=_Q, headers=_ME)
        assert response.status_code == 504
        assert _sample(tier, _BUDGET) == 1
    finally:
        await tier.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_a_plain_downstream_502_is_not_budget_exhausted() -> None:
    gw = _MockAigateway((_MODEL,), responses={_MODEL: (401, {"message": "bad key"})})
    client = gw.client()
    tier = await build_node_tier(
        env={},
        config=_config(),
        client=client,
        settings=NodeTierSettings(request_timeout_s=5.0, aigateway_timeout_s=4.0),
        artifact_store=_NEVER_SPILLS,
        artifact_signing_key=_KEY,
    )
    try:
        async with _node_client(tier) as node:
            response = await node.get(f"/{_MODEL}", params=_Q, headers=_ME)
        assert response.status_code == 502
        assert _sample(tier, _BUDGET) == 0
    finally:
        await tier.aclose()
        await client.aclose()


# --- one histogram sample per request, with the FINAL status ----------------------------------


@pytest.mark.asyncio
async def test_a_spill_timeout_records_one_sample_with_the_final_502() -> None:
    store = _CountingSlowStore(5.0)

    async def big(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"B" * 64})

    tier = _direct_tier(
        big,
        spill_timeout_s=0.1,
        result_inline_cap_bytes=10,
        result_hard_cap_bytes=1000,
        store=store,
    )
    try:
        async with _node_client(tier) as node:
            response = await node.get("/anything", headers=_ME)
        assert response.status_code == 502
        assert _duration_samples(tier) == {"502": 1.0}
    finally:
        store.release.set()


@pytest.mark.asyncio
async def test_a_remapped_500_records_one_sample_with_the_final_502() -> None:
    async def downstream(scope: Any, receive: Any, send: Any) -> None:
        body = b'{"error": {"code": "aigateway_http_401", "message": "bad key"}}'
        await send({"type": "http.response.start", "status": 500, "headers": []})
        await send({"type": "http.response.body", "body": body})

    tier = _direct_tier(downstream)
    async with _node_client(tier) as node:
        response = await node.get("/anything", headers=_ME)
    assert response.status_code == 502
    assert _duration_samples(tier) == {"502": 1.0}


# --- FX-13 amended, and the build order -------------------------------------------------------


def test_inverted_caps_are_not_refused_because_the_hard_cap_already_wins() -> None:
    NodeTierSettings(result_inline_cap_bytes=101, result_hard_cap_bytes=100).validate()


@pytest.mark.asyncio
async def test_the_store_is_checked_before_the_world_is_built() -> None:
    """A refused store must fail the build before the world (and its collision guard) exists."""
    config = parse_config(
        tomllib.loads('[data]\n"/token" = { value = "shadowed" }\n'),
        {},
        registry=EMPTY_MODEL_WORLD,
    )
    readiness = NodeReadiness()
    with pytest.raises(NodeTierError, match="OME-929"):
        await build_node_tier(env={}, config=config, engine_routes={"/token"}, readiness=readiness)
    assert readiness.ready is False


def test_the_package_does_not_re_export_the_private_tier_config() -> None:
    from screamingface_engine.world.node_tier.build import _tier_config

    assert callable(_tier_config)
    assert not hasattr(node_tier, "_tier_config")
