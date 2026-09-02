"""OME-1026 U3 — ``/v1/models`` private path: the wait ceiling and the cache policy.

FEATURE: implicit live discovery must not change what ``/v1/models`` costs or leaks.
The caller waits at most the clamped user budget for a private refresh — the WORK is
never cancelled and publishes for the next request — and every response class now
carries the account-scoped cache policy, because the body is credential-derived.

INVARIANT (bounds the WAIT, never the WORK): a private refresh that outlives the
budget keeps running; the request that abandoned it serves seeds; the finished
snapshot answers the next request — with exactly ONE upstream dial in total.

INVARIANT (concurrency): the private snapshot is gathered CONCURRENTLY with the
public listings, so adding a credential-scoped provider does not serialize the
route into a sum of provider budgets.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.parameter_discovery import DiscoveryError, DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.live_models import LIVE_MODELS_URL
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings
from aigateway.routes.private_cache import CACHE_CONTROL

_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_A_KEY = "sk-ant-account-a-key"
# A deadlock bound, not a timing assumption — the happy path releases in milliseconds.
_RENDEZVOUS_TIMEOUT_S = 8.0


class _Clock:
    def now(self) -> float:
        return 1_000.0


def _portal(client: TestClient):
    portal = client.portal
    assert portal is not None, "the TestClient must be entered as a context manager"
    return portal


def _anthropic_body(models: list[str]) -> RawResponse:
    body = json.dumps({"data": [{"id": m, "type": "model"} for m in models], "has_more": False})
    return RawResponse(status=200, content_type="application/json", body=body)


class _GatedClient:
    """The private dial parks on a gate the TEST releases — after the route answered."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.keys_seen: list[str] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert url == _FIRST_PAGE, f"unexpected dial: {url}"
        self.keys_seen.append(headers["x-api-key"])
        async with asyncio.timeout(_RENDEZVOUS_TIMEOUT_S):
            await self.gate.wait()
        return _anthropic_body(["claude-a-only"])


class _RendezvousClient:
    """Each scope's dial completes only once the OTHER scope's dial has STARTED.

    # WHY this proves concurrency without a wall clock: a sequential composition
    # never has both dials in flight, so neither rendezvous is met, both refreshes
    # fail, and the route can only serve seeds. Live rows for BOTH providers are
    # therefore possible ONLY if the route gathered the two scopes concurrently.
    """

    def __init__(self) -> None:
        self.anthropic_started = asyncio.Event()
        self.openrouter_started = asyncio.Event()

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        if url == LIVE_MODELS_URL:
            self.openrouter_started.set()
            await self._meet(self.anthropic_started)
            body = json.dumps(
                {"data": [{"id": "qwen/qwen3-coder"}], "links": {"next": None}, "total_count": 1}
            )
            return RawResponse(status=200, content_type="application/json", body=body)
        assert url == _FIRST_PAGE, f"unexpected dial: {url}"
        self.anthropic_started.set()
        await self._meet(self.openrouter_started)
        return _anthropic_body(["claude-a-only"])

    @staticmethod
    async def _meet(other_started: asyncio.Event) -> None:
        try:
            async with asyncio.timeout(_RENDEZVOUS_TIMEOUT_S):
                await other_started.wait()
        except TimeoutError as exc:  # pragma: no cover — the sequential-failure path
            raise DiscoveryError("rendezvous never met: scopes ran sequentially") from exc


class _InstantAnthropicClient:
    """The plainest healthy private page — used only to land the publication warm."""

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert url == _FIRST_PAGE, f"unexpected dial: {url}"
        return _anthropic_body(["claude-a-only"])


class _LoudClient:
    def __init__(self) -> None:
        self.dialed: list[str] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        self.dialed.append(url)
        raise AssertionError(f"forbidden discovery egress: {url}")


def _configure(monkeypatch: pytest.MonkeyPatch) -> AnthropicPluginSettings:
    settings = AnthropicPluginSettings()
    monkeypatch.setattr(anthropic_plugin_module.PLUGIN, "settings", settings)
    return settings


def _install(client: TestClient, http: Any, *, timeout_s: float = 3.0) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(timeout_s=timeout_s),
    )
    app.state.model_catalog = ModelCatalog(clock=_Clock())


def _accept_any_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


def _store_default_key(client: TestClient) -> None:
    response = client.put("/v1/auth/anthropic/profiles/default/api-key", json={"api_key": _A_KEY})
    assert response.status_code == 200, response.text


def _create_connection(client: TestClient, label: str, api_key: str) -> None:
    response = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "anthropic", "label": label, "api_key": api_key},
    )
    assert response.status_code == 201, response.text


def _anthropic_ids(client: TestClient) -> list[str]:
    response = client.get("/v1/models")
    assert response.status_code == 200, response.text
    return [r["id"] for r in response.json()["data"] if r["owned_by"] == "anthropic"]


def _seed_ids(settings: AnthropicPluginSettings) -> list[str]:
    return [f"anthropic/{entry.model_name}" for entry in settings.models]


# ── implicit ambiguity ─────────────────────────────────────────────────────────


def test_default_plus_another_connection_serves_seeds_with_zero_egress(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _LoudClient()
    _install(authenticated_client, http)
    _create_connection(authenticated_client, "default", "sk-ant-default")
    _create_connection(authenticated_client, "other", "sk-ant-other")

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == []


# ── the wait ceiling ──────────────────────────────────────────────────────────


def test_the_budget_bounds_the_wait_and_never_the_work(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _GatedClient()
    # WHY a small configured dial: ``user_wait_budget`` clamps to min(timeout_s, 3.0),
    # so this is the ONE knob that keeps the bounded-wait assertion off a real 3 s.
    _install(authenticated_client, http, timeout_s=0.2)
    _store_default_key(authenticated_client)

    # The refresh is parked on the gate, so a live listing is impossible: seeds
    # within the budget prove the wait is bounded while the work is still running.
    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.keys_seen == [_A_KEY], "the refresh started (and was not re-dialled)"

    app = cast(FastAPI, authenticated_client.app)

    async def _release_and_drain() -> None:
        http.gate.set()
        await app.state.profile_model_catalog.drain()

    _portal(authenticated_client).call(_release_and_drain)

    assert _anthropic_ids(authenticated_client) == ["anthropic/claude-a-only"], (
        "the abandoned refresh finished and published for the next request"
    )
    assert http.keys_seen == [_A_KEY], "one dial in total: bounded wait cancelled nothing"


def test_private_and_public_scopes_refresh_concurrently(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )
    _accept_any_api_key(monkeypatch)
    app = cast(FastAPI, authenticated_client.app)
    _install(authenticated_client, _InstantAnthropicClient())
    _store_default_key(authenticated_client)
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]

    async def _reset_private_catalog() -> None:
        # Land the publication warm, then retire its snapshot: the listing below
        # must refresh BOTH scopes on one request for the rendezvous to be met.
        await app.state.profile_model_catalog.drain()
        app.state.profile_model_catalog.invalidate(
            account_id=account_id, provider="anthropic", profile_name="default"
        )

    _portal(authenticated_client).call(_reset_private_catalog)
    _install(authenticated_client, _RendezvousClient())

    rows = authenticated_client.get("/v1/models").json()["data"]
    ids = [r["id"] for r in rows]

    assert "anthropic/claude-a-only" in ids
    assert "openrouter/qwen/qwen3-coder" in ids


# ── the cache policy on every response class ──────────────────────────────────


def test_a_successful_listing_carries_the_private_cache_policy(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    response = authenticated_client.get("/v1/models")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    vary = {token.strip().lower() for token in response.headers["Vary"].split(",")}
    assert {"authorization", "x-user-email"} <= vary


def test_an_unauthenticated_refusal_carries_the_same_policy(client: TestClient) -> None:
    """The 401 is raised while SOLVING dependencies — only a route class covers it."""
    response = client.get("/v1/models")

    assert response.status_code == 401
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    vary = {token.strip().lower() for token in response.headers["Vary"].split(",")}
    assert {"authorization", "x-user-email"} <= vary
