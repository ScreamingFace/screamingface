"""OME-627: the discovery runtime is constructed once and reaches ONLY the detail route.

Phase 3 (OME-479) §5.2/§5.3: discovery is bounded, cached, and off the chat critical
path. These tests pin the wiring itself — that the composition root builds the
runtime under the configured bounds, that the detailed contract publishes a real
freshness window instead of a constant, and that chat dispatch cannot reach
discovery at all.
"""

from __future__ import annotations

import inspect
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import State

from aigateway.config import Settings
from aigateway.core.auth_types import AuthType
from aigateway.core.credential_names import profile_id_for
from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState
from aigateway.main import create_app
from aigateway.routes import chat, chat_dispatch

_MODEL = "anthropic/claude-opus-4-8"


def _state(client: TestClient) -> State:
    # ``TestClient.app`` is typed as a bare ASGI callable; the app under test is
    # always the FastAPI instance the fixture built.
    return cast(FastAPI, client.app).state


async def _seed_profile(credential_blobs, account_id: str, *, auth_type: AuthType) -> None:
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type=auth_type,
        )
    )


# --- construction ------------------------------------------------------------


def test_app_exposes_one_runtime_built_under_the_configured_bounds(
    client: TestClient,
) -> None:
    runtime = _state(client).discovery_runtime
    assert isinstance(runtime, DiscoveryRuntime)

    settings: Settings = _state(client).settings
    assert runtime.limits.timeout_s == settings.discovery_timeout_seconds
    assert runtime.limits.max_bytes == settings.discovery_max_bytes
    assert runtime.cache.limits.ttl_s == settings.discovery_cache_ttl_seconds
    assert runtime.cache.limits.stale_ttl_s == settings.discovery_cache_stale_ttl_seconds
    assert runtime.cache.limits.max_entries == settings.discovery_cache_max_entries


@pytest.mark.asyncio
async def test_the_runtime_and_its_cache_survive_between_requests(
    credential_blobs, authenticated_client
) -> None:
    # A per-request runtime would rebuild an empty cache every time, turning the
    # TTL into a no-op and re-dialling the public source on every contract read.
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    await _seed_profile(credential_blobs, account_id, auth_type="api_key")
    before = _state(authenticated_client).discovery_runtime

    for _ in range(2):
        resp = authenticated_client.get("/v1/model-parameters", params={"model": _MODEL})
        assert resp.status_code == 200, resp.text

    after = _state(authenticated_client).discovery_runtime
    assert after is before
    assert after.cache is before.cache


def test_disabling_discovery_leaves_no_runtime_rather_than_an_unbounded_one(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AIGW_DISCOVERY_ENABLED", "false")
    app = create_app(Settings())
    assert app.state.discovery_runtime is None


# --- the detail contract publishes a real window -----------------------------


@pytest.mark.asyncio
async def test_detail_contract_publishes_the_locked_v1_freshness_window(
    credential_blobs, authenticated_client
) -> None:
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    await _seed_profile(credential_blobs, account_id, auth_type="api_key")

    body = authenticated_client.get("/v1/model-parameters", params={"model": _MODEL}).json()

    # anthropic declares no dynamic source yet, so the contract is static-only:
    # never observed, and therefore neither stale nor degraded.
    assert body["freshness"] == {
        "observed_at": None,
        "expires_at": None,
        "stale": False,
        "degraded": False,
    }


@pytest.mark.asyncio
async def test_detail_contract_still_serves_when_discovery_is_switched_off(
    credential_blobs, authenticated_client
) -> None:
    # Turning discovery off must degrade the EVIDENCE, never the endpoint: the
    # contract is still composed from the provider's static observations.
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    await _seed_profile(credential_blobs, account_id, auth_type="api_key")
    _state(authenticated_client).discovery_runtime = None

    resp = authenticated_client.get("/v1/model-parameters", params={"model": _MODEL})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["freshness"] == {
        "observed_at": None,
        "expires_at": None,
        "stale": False,
        "degraded": False,
    }
    assert body["parameters"]  # static evidence still composes a real contract


# --- chat dispatch cannot discover -------------------------------------------


def test_chat_dispatch_modules_reference_no_discovery_machinery() -> None:
    # INVARIANT (§5.2): no chat request ever waits on a network discovery. The
    # cheapest durable proof is structural — the dispatch path holds no reference
    # to the runtime, the cache, or the provider discovery hook, so there is no
    # call site to regress. A behavioural test could only show that TODAY's inputs
    # happen not to reach one.
    forbidden = (
        "discovery_runtime",
        "DiscoveryRuntime",
        "ObservationCache",
        "discover_chat_parameter_snapshot",
        "chat_discovery_source",
    )
    for module in (chat, chat_dispatch):
        source = inspect.getsource(module)
        for token in forbidden:
            assert token not in source, f"{module.__name__} references {token}"
