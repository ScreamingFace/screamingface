"""OME-1026 final pass F2 — 3 seconds is a HARD maximum, not a default.

FEATURE: a bounded model listing. Neither the global catalog nor a profile's private
catalog may hold a caller longer than three seconds, whatever the operator
configured for a provider dial.

STORY: as an operator I raise ``AIGW_DISCOVERY_TIMEOUT_SECONDS`` to 10 because one
provider paginates slowly, and my users still get their model list promptly.

INVARIANT (the defect this closes): the routes read the configured discovery timeout
DIRECTLY, and the setting accepts any positive value. So the reviewed "3-second
user-facing budget" was only the default of a knob an operator could turn to 30 —
the budget and the dial deadline were the same number wearing two hats.

INVARIANT (the cap is a maximum, not an override): a deployment that configures 1.5 s
keeps 1.5 s. Raising the floor would make every listing slower for the sake of a
bound that already held.

INVARIANT (expiry never cancels): the wait and the work stay separate objects. When
the budget runs out the caller is released and the shared refresh keeps running, so a
later request observes its snapshot.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.config import Settings
from aigateway.core.background_refresh import BackgroundRefreshManager
from aigateway.core.discovery_budget import MAX_USER_WAIT_S, user_wait_budget
from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.profile_model_catalog import build_profile_model_catalog
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.live_models import LIVE_MODELS_URL
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings
from tests.conftest import drain_private_catalog

_LIVE_ID = "openai/gpt-5-budgeted"
_ANTHROPIC_ID = "claude-budgeted-4-9"
_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_A_KEY = "sk-ant-budget-a"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _WaitProbe:
    """Records every user-facing wait budget, then waits a scaled-down one for real.

    # WHY the recorded budget is SUBSTITUTED rather than honoured: the claim under test
    # is which VALUE the production code chose — three seconds rather than the
    # operator's ten. Actually sleeping three seconds per expiry case would add wall
    # clock and no information.
    # WHY it still delegates to the real ``wait_up_to``: the expiry SEMANTICS are half
    # the invariant. A stub returning ``task.done()`` would report "unfinished" for a
    # refresh that completes in microseconds off a warm cache, so the payoff assertion
    # would fail against correct code. The genuine waiter distinguishes "parked
    # upstream, budget spent" from "already published".
    """

    _SUBSTITUTE_S = 0.5

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.budgets: list[float] = []
        real = BackgroundRefreshManager.wait_up_to

        async def _probe(inner: Any, task: asyncio.Task[Any], *, timeout: float) -> bool:
            self.budgets.append(timeout)
            return await real(inner, task, timeout=self._SUBSTITUTE_S)

        monkeypatch.setattr(BackgroundRefreshManager, "wait_up_to", _probe)


class _ParkedCatalog:
    """A public catalog dial that answers only once the test releases it."""

    def __init__(self, ids: list[str]) -> None:
        self._body = json.dumps(
            {"data": [{"id": i} for i in ids], "links": {"next": None}, "total_count": len(ids)}
        )
        self.release = asyncio.Event()
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        await self.release.wait()
        return RawResponse(status=200, content_type="application/json", body=self._body)


class _ParkedPrivateCatalog:
    """A credentialed catalog dial that answers only once the test releases it."""

    def __init__(self) -> None:
        self._body = json.dumps(
            {"data": [{"id": _ANTHROPIC_ID, "type": "model"}], "has_more": False}
        )
        self.release = asyncio.Event()
        self.keys_seen: list[str] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert headers is not None, "a private catalog dial must carry a credential"
        self.keys_seen.append(headers["x-api-key"])
        assert url == _FIRST_PAGE, url
        await self.release.wait()
        return RawResponse(status=200, content_type="application/json", body=self._body)


def _runtime(http: Any, *, timeout_s: float) -> DiscoveryRuntime:
    return DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(timeout_s=timeout_s),
    )


# ── the helper itself ─────────────────────────────────────────────────────────


def test_the_cap_is_a_maximum_and_not_an_override() -> None:
    assert MAX_USER_WAIT_S == 3.0
    assert user_wait_budget(10.0) == 3.0
    assert user_wait_budget(30.0) == 3.0
    # Below the cap the operator's own, lower value survives untouched.
    assert user_wait_budget(1.5) == 1.5
    assert user_wait_budget(3.0) == 3.0


def test_a_generous_provider_timeout_does_not_reach_the_profile_catalogs_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The private listing's budget, read off real Settings from the real env var."""
    monkeypatch.setenv("AIGW_DISCOVERY_TIMEOUT_SECONDS", "10")
    settings = Settings()
    assert settings.discovery_timeout_seconds == 10.0, "the env var must really be 10"

    catalog = build_profile_model_catalog(settings=settings)

    assert catalog is not None
    assert catalog.wait_budget_s == 3.0


def test_a_lower_configured_timeout_still_bounds_the_profile_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIGW_DISCOVERY_TIMEOUT_SECONDS", "1.5")

    catalog = build_profile_model_catalog(settings=Settings())

    assert catalog is not None
    assert catalog.wait_budget_s == 1.5


# ── the global listing ────────────────────────────────────────────────────────


def test_the_global_listing_waits_at_most_three_seconds_and_keeps_refreshing(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configured 10 s, waited 3 s, refresh still alive, later request sees it."""
    settings = OpenRouterPluginSettings(enabled=True, default_models=["openrouter/openai/seed"])
    monkeypatch.setattr(openrouter_plugin_module.PLUGIN, "settings", settings)
    http = _ParkedCatalog([_LIVE_ID])
    probe = _WaitProbe(monkeypatch)
    app = cast(FastAPI, authenticated_client.app)
    app.state.discovery_runtime = _runtime(http, timeout_s=10.0)
    app.state.model_catalog = ModelCatalog(clock=_Clock())

    cold = authenticated_client.get("/v1/models")

    assert cold.status_code == 200, cold.text
    cold_ids = [row["id"] for row in cold.json()["data"] if row["owned_by"] == "openrouter"]
    assert cold_ids == ["openrouter/openai/seed"], cold_ids
    # THE assertion: the route asked for 3 s even though the provider dial may take 10.
    assert probe.budgets == [3.0], probe.budgets
    assert http.dialed == [LIVE_MODELS_URL], "the refresh must have started anyway"
    assert app.state.public_refreshes.inflight == 1, "expiry must not cancel the refresh"

    # Release it, land it in the app's own loop, and read the payoff.
    portal = authenticated_client.portal
    assert portal is not None
    portal.call(http.release.set)
    portal.call(app.state.public_refreshes.drain)

    warm_ids = [
        row["id"]
        for row in authenticated_client.get("/v1/models").json()["data"]
        if row["owned_by"] == "openrouter"
    ]
    assert f"openrouter/{_LIVE_ID}" in warm_ids, warm_ids
    assert http.dialed == [LIVE_MODELS_URL], "one upstream fetch served both requests"
    # Every wait this route performed — cold and warm — was capped.
    assert set(probe.budgets) == {3.0}, probe.budgets


# ── the profile listing ───────────────────────────────────────────────────────


def test_the_profile_listing_waits_at_most_three_seconds_and_keeps_refreshing(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    anthropic_live_discovery: Any,
) -> None:
    """Same bound on the private path, which has its own budget object."""
    monkeypatch.setenv("AIGW_DISCOVERY_TIMEOUT_SECONDS", "10")
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

    http = _ParkedPrivateCatalog()
    app = cast(FastAPI, authenticated_client.app)
    app.state.discovery_runtime = _runtime(http, timeout_s=10.0)
    # The catalog the app is holding was built from the DEFAULT settings; rebuild it
    # from the 10-second configuration this case is about.
    rebuilt = build_profile_model_catalog(settings=Settings())
    assert rebuilt is not None, "discovery is enabled in this suite"
    app.state.profile_model_catalog = rebuilt
    assert rebuilt.wait_budget_s == 3.0

    probe = _WaitProbe(monkeypatch)
    stored = authenticated_client.put(
        "/v1/auth/anthropic/profiles/work/api-key", json={"api_key": _A_KEY}
    )
    assert stored.status_code == 200, stored.text

    listing = authenticated_client.get("/v1/auth/anthropic/profiles/work/models")

    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["status"] == "refreshing", body
    assert body["reason"] is None, body
    # The post-commit warm-up uses a zero budget (start-only), so the budgets recorded
    # here are the REQUEST's, and every one of them is capped.
    assert probe.budgets and set(probe.budgets) == {3.0}, probe.budgets

    portal = authenticated_client.portal
    assert portal is not None
    portal.call(http.release.set)
    drain_private_catalog(authenticated_client)

    warm = authenticated_client.get("/v1/auth/anthropic/profiles/work/models").json()
    assert warm["status"] == "fresh", warm
    assert [row["id"] for row in warm["data"]] == [f"anthropic/{_ANTHROPIC_ID}"], warm
    assert http.keys_seen == [_A_KEY], http.keys_seen


def test_the_anthropic_seed_listing_is_what_a_refreshing_profile_shows(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    anthropic_live_discovery: Any,
) -> None:
    """The honest payload while the budget is spent: the provider's compiled seeds."""
    seeds = {
        f"anthropic/{entry.model_name}"
        for entry in anthropic_plugin_module.PLUGIN.register_models()
    }
    assert f"anthropic/{_ANTHROPIC_ID}" not in seeds, "the live id must not be a seed"
