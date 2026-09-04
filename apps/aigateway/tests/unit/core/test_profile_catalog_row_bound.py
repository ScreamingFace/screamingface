"""OME-1026 final pass F7 — the row budget is a HARD bound, end to end.

FEATURE: a private model cache whose footprint an operator can predict from
configuration alone, whatever any provider's catalog turns out to contain.

STORY: as an operator I set ``AIGW_DISCOVERY_PROFILE_CACHE_MAX_ROWS`` and that number
holds — a tenant whose provider returns an enormous catalog cannot push this process
past it, and cannot make the gateway re-dial upstream on every page load either.

INVARIANT (no carve-out — owner decision): ``retained_rows`` never exceeds
``max_rows``. A single snapshot larger than the whole budget is refused rather than
cached; the refusal is recorded as a sanitized damped failure, and the identity keeps
its last good snapshot so stale still beats seeds.

INVARIANT (a refusal must not become an egress amplifier): an identity that can never
cache would otherwise dial the provider with the caller's own credential on every
request. The provider's declared ``failure_ttl_s`` suppresses that, and the suppression
expires — this is damping, not a permanent refusal.

AIDEV-NOTE: this file drives the REAL route with a canned transport, so it pins the
bound where an operator experiences it rather than only at the store's own API (that
is ``test_profile_snapshot_memory_bound.py``).
"""

from __future__ import annotations

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
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.profile_model_catalog import ProfileModelCatalog
from aigateway.core.profile_snapshot_store import CACHE_BUDGET_REASON
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from tests.conftest import drain_private_catalog

_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_LIST_URL = "/v1/auth/anthropic/profiles/{name}/models"
_KEY = "sk-ant-rowbound"
_MAX_ROWS = 6


class _Clock:
    """A clock the test advances, so TTL expiry is a step and not a wait."""

    def __init__(self) -> None:
        self.value = 1_000.0

    def now(self) -> float:
        return self.value


class _SizedCatalog:
    """A credentialed catalog whose SIZE the test controls between dials."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.dials = 0

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert headers is not None, "the private catalog must be dialed WITH a credential"
        assert url == _FIRST_PAGE, url
        self.dials += 1
        body = json.dumps(
            {
                "data": [{"id": f"claude-row-{i}", "type": "model"} for i in range(self.count)],
                "has_more": False,
            }
        )
        return RawResponse(status=200, content_type="application/json", body=body)


def _setup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, http: _SizedCatalog
) -> tuple[ProfileModelCatalog, _Clock]:
    """Install a canned transport and a catalog with a SMALL, test-owned row budget."""
    monkeypatch.setattr(
        anthropic_plugin_module.PLUGIN, "settings", AnthropicPluginSettings(live_models=True)
    )

    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    clock = _Clock()
    # WHY the catalog is replaced rather than the env var set: the app-lifetime catalog is
    # built during ``create_app``, before any test body runs. Constructing it here also
    # lets the test own the clock, which is what makes TTL expiry a step instead of a wait.
    catalog = ProfileModelCatalog(
        clock=clock, max_identities=64, max_inflight_refreshes=8, max_rows=_MAX_ROWS
    )
    app.state.profile_model_catalog = catalog
    return catalog, clock


def _store_key(client: TestClient, *, name: str, key: str = _KEY) -> None:
    stored = client.put(f"/v1/auth/anthropic/profiles/{name}/api-key", json={"api_key": key})
    assert stored.status_code == 200, stored.text


def _listing(client: TestClient, *, name: str) -> dict:
    response = client.get(_LIST_URL.format(name=name))
    assert response.status_code == 200, response.text
    return response.json()


# ── an oversized catalog is refused, not cached and not truncated ──────────────


def test_an_oversized_private_catalog_is_refused_and_reported(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline: 20 rows against a 6-row budget retains NOTHING and says why."""
    http = _SizedCatalog(count=20)
    catalog, _clock = _setup(authenticated_client, monkeypatch, http)
    _store_key(authenticated_client, name="work")
    drain_private_catalog(authenticated_client)

    body = _listing(authenticated_client, name="work")

    assert body["status"] == "fallback", body
    assert body["reason"] == CACHE_BUDGET_REASON, body
    assert catalog.retained_rows == 0, catalog.retained_rows
    assert catalog.retained_rows <= catalog.max_rows
    # Not truncated either: the fallback payload is the provider's compiled seeds, and a
    # seed id is not one of the 20 rows the upstream returned.
    ids = {row["id"] for row in body["data"]}
    assert ids and not any(row_id.startswith("anthropic/claude-row-") for row_id in ids), ids


def test_a_refused_oversized_catalog_is_not_redialed_on_every_request(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Damping, where it matters: the caller's credential is not spent per page load."""
    http = _SizedCatalog(count=20)
    _setup(authenticated_client, monkeypatch, http)
    _store_key(authenticated_client, name="work")
    drain_private_catalog(authenticated_client)
    dials_after_first = http.dials
    assert dials_after_first >= 1, "the premise is that one dial happened"

    for _ in range(5):
        assert _listing(authenticated_client, name="work")["reason"] == CACHE_BUDGET_REASON
        drain_private_catalog(authenticated_client)

    assert http.dials == dials_after_first, "a refused catalog must be damped, not re-dialed"


def test_a_stale_snapshot_beats_seeds_when_an_oversized_replacement_is_refused(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The identity keeps its last good answer: what the credential actually returned.

    # WHY stale beats seeds here specifically: the seeds are a compiled guess about the
    # provider, while the stale rows are what THIS profile's own credential returned. A
    # refusal is a reason to stop trusting the new answer, not the old one.
    """
    http = _SizedCatalog(count=4)
    catalog, clock = _setup(authenticated_client, monkeypatch, http)
    _store_key(authenticated_client, name="work")
    drain_private_catalog(authenticated_client)
    fresh = _listing(authenticated_client, name="work")
    assert fresh["status"] == "fresh", fresh
    assert catalog.retained_rows == 4

    # The upstream catalog grows past the budget, and the cached snapshot ages out of
    # its TTL so a refresh is owed.
    http.count = 50
    source = anthropic_plugin_module.PLUGIN.model_discovery_source()
    assert source is not None
    clock.value += source.ttl_s + 1.0

    served = _listing(authenticated_client, name="work")
    drain_private_catalog(authenticated_client)
    settled = _listing(authenticated_client, name="work")

    assert settled["status"] == "stale", (served, settled)
    assert settled["reason"] == CACHE_BUDGET_REASON, settled
    assert [row["id"] for row in settled["data"]] == [
        f"anthropic/claude-row-{i}" for i in range(4)
    ], settled
    assert catalog.retained_rows == 4, "the refusal did not destroy the last good snapshot"
    assert catalog.retained_rows <= catalog.max_rows


def test_the_bound_holds_across_many_profiles(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each snapshot fits; the CUMULATIVE total is what the bound is really about."""
    http = _SizedCatalog(count=4)
    catalog, _clock = _setup(authenticated_client, monkeypatch, http)

    for index in range(5):
        name = f"p{index}"
        _store_key(authenticated_client, name=name, key=f"{_KEY}-{index}")
        drain_private_catalog(authenticated_client)
        assert _listing(authenticated_client, name=name)["status"] in {"fresh", "stale"}
        assert catalog.retained_rows <= catalog.max_rows, (index, catalog.retained_rows)

    # 5 profiles x 4 rows = 20 wanted, 6 allowed: the LRU gave up the oldest identities.
    assert catalog.retained_rows <= _MAX_ROWS
    assert catalog.tracked_identities < 5, catalog.tracked_identities
