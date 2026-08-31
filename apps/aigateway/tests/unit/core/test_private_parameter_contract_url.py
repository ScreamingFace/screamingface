"""OME-1026 remediation F4 — every private row's advertised detail URL must resolve.

FEATURE: one honest contract surface. A row published by the private profile listing
carries a ``parameter_contract_url``, and that URL is a promise: following it in the
same account/profile context returns the model's parameter contract.

STORY: as a profile owner I click through from a discovered model to its parameter
contract and get the contract — not a 404 for a model the gateway just listed to me.

INVARIANT (the leak this must NOT open): a private id is resolvable ONLY inside the
context that discovered it. Another account asking for the same id, and the same
account asking under a different profile, must still get ``model_not_found`` — the
private snapshot is never widened into the global catalog or a sibling profile.
"""

from __future__ import annotations

import json
from typing import Any, cast
from urllib.parse import unquote

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
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from tests.conftest import drain_private_catalog

_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_LIST_URL = "/v1/auth/anthropic/profiles/{name}/models"
# A model id that exists ONLY in the canned private catalog — never a compiled seed.
_DISCOVERED = "claude-private-only-4-9"
_A_KEY = "sk-ant-contract-a"
_B_KEY = "sk-ant-contract-b"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _CatalogClient:
    """A credentialed catalog whose rows depend on the calling key."""

    def __init__(self) -> None:
        self._per_key = {_A_KEY: [_DISCOVERED], _B_KEY: ["claude-b-only-4-9"]}
        self.keys_seen: list[str] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert headers is not None, "the private catalog must be dialed WITH a credential"
        key = headers["x-api-key"]
        self.keys_seen.append(key)
        if url != _FIRST_PAGE:
            raise AssertionError(f"unexpected dial: {url}")
        body = json.dumps(
            {
                "data": [{"id": model_id, "type": "model"} for model_id in self._per_key[key]],
                "has_more": False,
            }
        )
        return RawResponse(status=200, content_type="application/json", body=body)


def _configure(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> AnthropicPluginSettings:
    settings = AnthropicPluginSettings(**overrides)
    monkeypatch.setattr(anthropic_plugin_module.PLUGIN, "settings", settings)
    return settings


def _accept_any_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


def _install(client: TestClient, http: Any) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )


def _store_key(client: TestClient, *, name: str, key: str, **kwargs: Any) -> None:
    stored = client.put(
        f"/v1/auth/anthropic/profiles/{name}/api-key", json={"api_key": key}, **kwargs
    )
    assert stored.status_code == 200, stored.text


def _advertised_url(client: TestClient, *, name: str, model_id: str) -> str:
    """The row's OWN ``parameter_contract_url`` — the promise under test."""
    listing = client.get(_LIST_URL.format(name=name))
    assert listing.status_code == 200, listing.text
    rows = {row["id"]: row for row in listing.json()["data"]}
    assert model_id in rows, f"the private listing did not publish {model_id}: {list(rows)}"
    return rows[model_id]["parameter_contract_url"]


# ── the promise: a discovered-only id resolves in its own context ───────────────


def test_a_discovered_only_private_id_resolves_through_its_advertised_url(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported defect, end to end: list, follow the row's own URL, get 200."""
    settings = _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    _store_key(authenticated_client, name="work", key=_A_KEY)

    canonical = f"anthropic/{_DISCOVERED}"
    # INVARIANT: this id is NOT a compiled seed, so nothing but the private snapshot
    # can resolve it — otherwise the test would pass without the fix.
    seeds = {entry.model_name for entry in anthropic_plugin_module.PLUGIN.register_models()}
    assert _DISCOVERED not in seeds and canonical not in seeds, seeds
    assert settings.live_models, "private discovery must be on for this file's premise"

    url = _advertised_url(authenticated_client, name="work", model_id=canonical)
    assert unquote(url).endswith(f"model={canonical}"), url

    contract = authenticated_client.get(url, headers={"X-Profile": "work"})

    assert contract.status_code == 200, contract.text
    body = contract.json()
    assert body["model"]["id"] == canonical, body
    assert body["model"]["upstream_id"] == _DISCOVERED, body
    # The document is per-account/profile, exactly like the listing that advertised it.
    assert body["context"]["scope"] == "account_profile", body["context"]


def test_a_compiled_seed_id_still_resolves_without_consulting_the_private_catalog(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lazy rule: a known id must not pay for a private snapshot read."""
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CatalogClient()
    _install(authenticated_client, http)
    _store_key(authenticated_client, name="work", key=_A_KEY)
    seed = anthropic_plugin_module.PLUGIN.register_models()[0].model_name
    canonical = f"anthropic/{seed}" if not seed.startswith("anthropic/") else seed
    # Barrier, not a sleep: publication starts a post-commit refresh in the app's own
    # loop, and its dial must be accounted for BEFORE the counter is reset.
    drain_private_catalog(authenticated_client)
    http.keys_seen.clear()

    contract = authenticated_client.get(
        "/v1/model-parameters", params={"model": canonical}, headers={"X-Profile": "work"}
    )

    assert contract.status_code == 200, contract.text
    assert http.keys_seen == [], "a seeded id must resolve offline"


# ── the isolation the widening must not break ─────────────────────────────────


def test_the_same_private_id_stays_unresolved_for_another_account(
    client: TestClient, provisioned_user_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Account B holds a profile of the same NAME — and still cannot resolve A's id."""
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    _install(client, _CatalogClient())

    login = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    )
    assert login.status_code == 200, login.text
    admin_token = login.json()["token"]
    provisioned_user_factory("private-contract-b")
    other = client.post(
        "/v1/auth/login",
        json={"username": "private-contract-b", "password": "test-user-password"},
    )
    assert other.status_code == 200, other.text
    other_token = other.json()["token"]

    # Account A discovers the id under profile "work".
    client.headers.update({"Authorization": f"Bearer {admin_token}"})
    _store_key(client, name="work", key=_A_KEY)
    canonical = f"anthropic/{_DISCOVERED}"
    url = _advertised_url(client, name="work", model_id=canonical)
    assert client.get(url, headers={"X-Profile": "work"}).status_code == 200

    # Account B, same profile name, its own credential and its own catalog.
    client.headers.update({"Authorization": f"Bearer {other_token}"})
    _store_key(client, name="work", key=_B_KEY)
    assert client.get(_LIST_URL.format(name="work")).status_code == 200

    leaked = client.get(url, headers={"X-Profile": "work"})

    assert leaked.status_code == 404, leaked.text
    assert leaked.json()["detail"]["code"] == "model_not_found"


def test_the_same_private_id_stays_unresolved_under_a_sibling_profile(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One account, two profiles: an id discovered under one is not the other's."""
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    _store_key(authenticated_client, name="work", key=_A_KEY)
    _store_key(authenticated_client, name="personal", key=_B_KEY)

    canonical = f"anthropic/{_DISCOVERED}"
    url = _advertised_url(authenticated_client, name="work", model_id=canonical)
    assert authenticated_client.get(url, headers={"X-Profile": "work"}).status_code == 200
    # Warm the sibling's own snapshot, so this is about IDENTITY and not about
    # whether the sibling profile has been discovered at all.
    assert authenticated_client.get(_LIST_URL.format(name="personal")).status_code == 200

    crossed = authenticated_client.get(url, headers={"X-Profile": "personal"})

    assert crossed.status_code == 404, crossed.text
    assert crossed.json()["detail"]["code"] == "model_not_found"


def test_a_private_id_never_enters_the_global_listing(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The structural boundary this widening must not cross."""
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    _store_key(authenticated_client, name="work", key=_A_KEY)
    canonical = f"anthropic/{_DISCOVERED}"
    assert _advertised_url(authenticated_client, name="work", model_id=canonical)

    listing = authenticated_client.get("/v1/models")

    assert listing.status_code == 200
    assert canonical not in {row["id"] for row in listing.json()["data"]}


def test_an_unknown_id_is_still_a_404_under_a_valid_profile(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The widening must not become a blanket accept."""
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    _store_key(authenticated_client, name="work", key=_A_KEY)

    missing = authenticated_client.get(
        "/v1/model-parameters",
        params={"model": "anthropic/claude-nonexistent-9-9"},
        headers={"X-Profile": "work"},
    )

    assert missing.status_code == 404, missing.text
    assert missing.json()["detail"]["code"] == "model_not_found"
