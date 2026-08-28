"""OME-629: the detail ROUTE actually carries observed catalog evidence.

FEATURE: model-specific provider evidence, end to end. The pure algebra is pinned
by ``test_openrouter_catalog_evidence``; this proves the seam — that
``/v1/model-parameters`` passes the runtime's snapshot through the plugin's overlay
instead of discarding it, which is the only thing that makes the observed evidence
reach a client.

INVARIANT: the runtime is driven through an INJECTED client. No test reaches the
public catalog (the suite-wide egress guard in ``conftest`` fails loudly if one
tries), and the model reaching discovery is one the canonical inventory already
validated.
"""

from __future__ import annotations

import json
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    RawResponse,
)
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.plugins.openrouter_provider.discovery import MODELS_URL
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_FLASH = "openrouter/google/gemini-2.0-flash-001"
_FABLE = "openrouter/anthropic/claude-fable-5"

_CATALOG = {
    "data": [
        {
            "id": "google/gemini-2.0-flash-001",
            "supported_parameters": ["temperature", "max_tokens", "seed", "top_k"],
        },
        {
            "id": "anthropic/claude-fable-5",
            "supported_parameters": ["temperature", "max_tokens"],
        },
    ]
}
_OPENAPI: dict[str, object] = {
    "components": {"schemas": {"ChatRequest": {"properties": {"temperature": {}}}}}
}


class _CatalogClient(DiscoveryHttpClient):
    """Injected transport: serves the fixture catalog, or fails on demand."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.calls.append(url)
        if self._error is not None:
            raise self._error
        body = _CATALOG if url == MODELS_URL else _OPENAPI
        return RawResponse(status=200, content_type="application/json", body=json.dumps(body))


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
def openrouter_enabled(monkeypatch) -> None:
    """Enable the plugin and seed exactly the two models the fixture catalog holds.

    # AIDEV-NOTE: patches the plugin INSTANCE, not the environment. ``PLUGIN`` is a
    # module-level singleton built at import time, and ``load_plugins`` hands that
    # same object to every app — so once any test module has imported the plugin,
    # ``AIGW_OPENROUTER_*`` set later cannot reach it and the models silently fail
    # to register. Assigning settings here is order-independent, and monkeypatch
    # restores the shared singleton on teardown.
    """
    from aigateway.plugins.openrouter_provider import plugin as plugin_module

    monkeypatch.setattr(
        plugin_module.PLUGIN,
        "settings",
        # OME-972 setup-only amendment: this suite pins the SEEDED catalog route —
        # live_models=False keeps its listing reads static. Assertions untouched.
        OpenRouterPluginSettings(enabled=True, live_models=False, default_models=[_FLASH, _FABLE]),
    )


def _install_runtime(client: TestClient, catalog_client: _CatalogClient, clock: _Clock) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=catalog_client,
        cache=ObservationCache(
            clock=clock, limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )


async def _seed_profile(credential_blobs, account_id: str) -> None:
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "openrouter", "default"),
            account_id=account_id,
            provider="openrouter",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )


async def _contract(credential_blobs, client: TestClient, model: str) -> dict:
    account_id = client.get("/v1/auth/me").json()["id"]
    await _seed_profile(credential_blobs, account_id)
    resp = client.get("/v1/model-parameters", params={"model": model})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_the_route_serves_the_seeded_openrouter_models(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    # Guards the precondition the rest of this module depends on: a disabled plugin
    # registers no models, so every assertion below would 404 on model_not_found
    # and prove nothing about the discovery seam.
    ids = {row["id"] for row in authenticated_client.get("/v1/models").json()["data"]}
    assert {_FLASH, _FABLE} <= ids


@pytest.mark.asyncio
async def test_the_route_publishes_the_observed_per_model_verdict(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    catalog_client = _CatalogClient()
    _install_runtime(authenticated_client, catalog_client, _Clock())

    body = await _contract(credential_blobs, authenticated_client, _FABLE)

    seed = body["parameters"]["seed"]
    # the fable row omits seed while the flash row lists it → a real negative.
    assert seed["provider"]["support"] == "unsupported"
    assert seed["provider"]["source"] == "openrouter:models"
    # …and the gateway still forwards it: evidence axis only.
    assert seed["gateway"]["status"] == "enabled"
    assert body["freshness"]["degraded"] is False
    assert body["freshness"]["observed_at"] is not None


@pytest.mark.asyncio
async def test_two_models_get_different_evidence_from_one_catalog(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    _install_runtime(authenticated_client, _CatalogClient(), _Clock())

    flash = await _contract(credential_blobs, authenticated_client, _FLASH)
    fable = await _contract(credential_blobs, authenticated_client, _FABLE)

    assert flash["parameters"]["seed"]["provider"]["support"] == "supported"
    assert fable["parameters"]["seed"]["provider"]["support"] == "unsupported"
    # the RULE projection is untouched: same statuses, same summary.
    shared = set(flash["parameters"]) & set(fable["parameters"])
    assert {p: flash["parameters"][p]["gateway"] for p in shared} == {
        p: fable["parameters"][p]["gateway"] for p in shared
    }


@pytest.mark.asyncio
async def test_a_catalog_outage_degrades_to_labelled_local_evidence(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    # No last-good value to fall back on: the contract must still serve, from the
    # provider's reviewed labelled-local evidence, and say so.
    _install_runtime(
        authenticated_client, _CatalogClient(error=DiscoveryError("unreachable")), _Clock()
    )

    body = await _contract(credential_blobs, authenticated_client, _FABLE)

    assert body["freshness"]["degraded"] is True
    assert body["parameters"]["seed"]["provider"]["source"] == "openrouter:static"
    assert "openrouter:models" not in {e["provider"]["source"] for e in body["parameters"].values()}


@pytest.mark.asyncio
async def test_the_stale_window_serves_the_last_good_verdict_flagged(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    # fresh read → TTL expiry → outage: the observed negative still stands, but the
    # client is told it is stale rather than being handed a silent fabrication.
    clock = _Clock()
    _install_runtime(authenticated_client, _CatalogClient(), clock)
    fresh = await _contract(credential_blobs, authenticated_client, _FABLE)
    assert fresh["parameters"]["seed"]["provider"]["stale"] is False

    runtime: DiscoveryRuntime = cast(FastAPI, authenticated_client.app).state.discovery_runtime
    # swap ONLY the transport, keeping the warm cache — that is the outage shape.
    runtime._client = _CatalogClient(error=DiscoveryError("unreachable"))  # noqa: SLF001
    clock.advance(61.0)

    stale = await _contract(credential_blobs, authenticated_client, _FABLE)
    assert stale["freshness"]["stale"] is True
    assert stale["parameters"]["seed"]["provider"]["support"] == "unsupported"
    assert stale["parameters"]["seed"]["provider"]["stale"] is True
