"""OME-972 U6 — every published id resolves; seeded reads stay catalog-free.

INVARIANT (lazy known-set): the detail route consults the live catalog ONLY on
a would-be 404 — a seeded or admitted id resolves with zero live-catalog work,
and an id published from a healthy snapshot resolves on its own contract
endpoint instead of 404ing. Chat dispatch stays membership-free: listing
changes never change what is dispatchable.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.plugins.openrouter_provider import plugin as plugin_module
from aigateway.plugins.openrouter_provider.discovery import MODELS_URL, OPENAPI_URL
from aigateway.plugins.openrouter_provider.live_models import LIVE_MODELS_URL
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

_DISCOVERED_UPSTREAM = "newvendor/newmodel"
_DISCOVERED = f"openrouter/{_DISCOVERED_UPSTREAM}"
# First compiled default seed — present without any explicit configuration.
_SEEDED = "openrouter/anthropic/claude-fable-5"
_SEEDED_UPSTREAM = _SEEDED.removeprefix("openrouter/")


@pytest.fixture
def openrouter_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True))


class _ServingClient:
    """All three OpenRouter public documents, in process, dials recorded."""

    def __init__(self) -> None:
        self.dialed: list[str] = []
        self._bodies: dict[str, Any] = {
            LIVE_MODELS_URL: {
                "data": [{"id": _DISCOVERED_UPSTREAM}],
                "links": {"next": None},
                "total_count": 1,
            },
            MODELS_URL: {
                "data": [
                    {"id": _DISCOVERED_UPSTREAM, "supported_parameters": ["temperature"]},
                    {"id": _SEEDED_UPSTREAM, "supported_parameters": ["temperature"]},
                ]
            },
            OPENAPI_URL: {
                "components": {"schemas": {"ChatRequest": {"properties": {"temperature": {}}}}}
            },
        }

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        # AIDEV-NOTE: loud, not KeyError. ``ModelCatalog`` converts a stray
        # exception into DiscoveryError("internal_error") -> seed fallback, so a
        # KeyError here would let an unexpected dial pass as a green test that
        # silently stopped exercising the live listing.
        if url not in self._bodies:
            raise AssertionError(f"canned client has no body for {url!r} — unexpected dial")
        return RawResponse(
            status=200, content_type="application/json", body=json.dumps(self._bodies[url])
        )


class _Clock:
    def now(self) -> float:
        return 1_000.0


def _install(client: TestClient) -> _ServingClient:
    http = _ServingClient()
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    app.state.model_catalog = ModelCatalog(clock=_Clock())
    return http


async def _upsert_profile(client: TestClient, credential_blobs: Any) -> None:
    account_id = client.get("/v1/auth/me").json()["id"]
    await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
        Profile(
            id=profile_id_for(account_id, "openrouter", "default"),
            account_id=account_id,
            provider="openrouter",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )


@pytest.mark.asyncio
async def test_a_discovered_id_resolves_on_its_own_contract_endpoint(
    openrouter_enabled, authenticated_client: TestClient, credential_blobs: Any
) -> None:
    _install(authenticated_client)
    await _upsert_profile(authenticated_client, credential_blobs)
    response = authenticated_client.get("/v1/model-parameters", params={"model": _DISCOVERED})
    # INVARIANT: what /v1/models publishes, /v1/model-parameters resolves — a
    # listed id that 404s on its own detail URL is a broken published contract.
    assert response.status_code == 200, response.text
    assert response.json()["model"]["id"] == _DISCOVERED


@pytest.mark.asyncio
async def test_an_id_absent_from_snapshot_and_seeds_still_404s(
    openrouter_enabled, authenticated_client: TestClient, credential_blobs: Any
) -> None:
    _install(authenticated_client)
    await _upsert_profile(authenticated_client, credential_blobs)
    response = authenticated_client.get(
        "/v1/model-parameters", params={"model": "openrouter/nope/not-here"}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "model_not_found"


@pytest.mark.asyncio
async def test_a_seeded_id_never_pays_for_a_live_catalog_read(
    openrouter_enabled, authenticated_client: TestClient, credential_blobs: Any
) -> None:
    http = _install(authenticated_client)
    await _upsert_profile(authenticated_client, credential_blobs)
    response = authenticated_client.get("/v1/model-parameters", params={"model": _SEEDED})
    assert response.status_code == 200, response.text
    # INVARIANT (lazy): the known-set hit short-circuits BEFORE the catalog —
    # the parameter-snapshot documents may be dialed, the listing never is.
    assert LIVE_MODELS_URL not in http.dialed


def test_chat_dispatch_is_membership_free_for_discovered_and_seeded_alike(
    openrouter_enabled, authenticated_client: TestClient
) -> None:
    _install(authenticated_client)
    body = {"messages": [{"role": "user", "content": "hi"}]}
    seeded = authenticated_client.post("/v1/chat/completions", json={"model": _SEEDED, **body})
    discovered = authenticated_client.post(
        "/v1/chat/completions", json={"model": _DISCOVERED, **body}
    )
    # WHY equality of ``detail``: with no credential profile, BOTH fail at the
    # same later stage with the same semantic error — proving the listing never
    # gates dispatch (a membership check would 404 the discovered id earlier,
    # with a different code). The ``_aigw`` envelope carries per-request
    # accounting metadata and is deliberately excluded.
    assert seeded.status_code == discovered.status_code
    assert seeded.json()["detail"] == discovered.json()["detail"]


def test_a_discovered_only_model_reaches_the_dispatch_boundary_with_a_credential(
    openrouter_enabled,
    authenticated_client: TestClient,
    credential_blobs: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The end of the acceptance chain: listed -> resolvable -> actually dispatched.

    The parity test above proves dispatch is membership-free by comparing
    refusals; this proves the positive case all the way to the provider
    boundary, so "every published id resolves via chat" rests on a request that
    really arrives at ``litellm.acompletion`` carrying the discovered id.
    """
    _install(authenticated_client)
    # Explicit test double: key READINESS is not what this test exercises —
    # dispatch reachability of a discovered-only id is.
    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)
    created = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "live-discovery", "api_key": "sk-or-v1-live"},
    )
    assert created.status_code == 201, created.text

    # The model is published ONLY by the live snapshot — it is in no seed list.
    assert _DISCOVERED not in OpenRouterPluginSettings(enabled=True).default_models
    listed = [row["id"] for row in authenticated_client.get("/v1/models").json()["data"]]
    assert _DISCOVERED in listed

    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            model_dump=lambda: {
                "id": "gen-live",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            }
        )

    with patch("litellm.acompletion", _fake_acompletion):
        response = authenticated_client.post(
            "/v1/chat/completions",
            json={"model": _DISCOVERED, "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200, response.text
    assert captured["model"] == _DISCOVERED
