"""OME-1026 U4 — ``/v1/model-parameters`` resolves the caller's effective credential.

FEATURE: implicit credential resolution for the detailed contract. The Python Client
sends no ``X-Profile``, so a discovered-only id must resolve for the caller's ONE
effective credential — hosted: the Profile named ``default``; local: the sole active
Connection — through the same shared resolver chat and ``/v1/models`` use.

STORY: as a local-mode user with one stored Anthropic key Connection, the
``parameter_contract_url`` advertised on my own listing rows resolves — without me
naming a profile — and describes exactly my credential's context.

INVARIANT (one request, ONE credential identity): the id is admitted from a snapshot
fetched under one durable credential revision; replacing the Connection's key between
admission and resolution is refused (409 ``credential_generation_changed``), never
answered with a document that mixes the two. Cross-account, ambiguous and unknown
resolutions stay ``model_not_found`` — the private id exists only in the context that
discovered it.
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

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
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from aigateway.routes import model_parameters as model_parameters_module

_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_PARAMS_URL = "/v1/model-parameters"
_KEY = "sk-ant-effective-credential"
# Exists ONLY in the canned private catalog, so nothing but the snapshot resolves it.
_DISCOVERED = "claude-implicit-only-4-9"
_PRIVATE_ID = f"anthropic/{_DISCOVERED}"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _CatalogClient:
    def __init__(self) -> None:
        self.keys_seen: list[str] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert headers is not None, "the private catalog must be dialed WITH a credential"
        self.keys_seen.append(headers["x-api-key"])
        assert url == _FIRST_PAGE, url
        body = json.dumps({"data": [{"id": _DISCOVERED, "type": "model"}], "has_more": False})
        return RawResponse(status=200, content_type="application/json", body=body)


def _setup(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> _CatalogClient:
    monkeypatch.setattr(
        anthropic_plugin_module.PLUGIN, "settings", AnthropicPluginSettings(live_models=True)
    )

    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)
    http = _CatalogClient()
    cast(FastAPI, client.app).state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    seeds = {entry.model_name for entry in anthropic_plugin_module.PLUGIN.register_models()}
    assert _DISCOVERED not in seeds, seeds
    return http


def _create_connection(client: TestClient, label: str, api_key: str = _KEY) -> str:
    response = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "anthropic", "label": label, "api_key": api_key},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _contract(client: TestClient, model: str, **request_kwargs: Any):
    # Deliberately NO X-Profile header: implicit resolution is the subject.
    return client.get(_PARAMS_URL, params={"model": model}, **request_kwargs)


# ── the effective credential resolves discovered-only ids ─────────────────────


def test_a_hosted_default_profile_resolves_a_discovered_id_without_x_profile(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(authenticated_client, monkeypatch)
    stored = authenticated_client.put(
        "/v1/auth/anthropic/profiles/default/api-key", json={"api_key": _KEY}
    )
    assert stored.status_code == 200, stored.text

    response = _contract(authenticated_client, _PRIVATE_ID)

    assert response.status_code == 200, response.text
    assert response.json()["model"]["upstream_id"] == _DISCOVERED, response.json()["model"]


def test_a_sole_active_connection_resolves_a_discovered_id_without_x_profile(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local mode: the Connection's label plays no part — it is the sole credential."""
    http = _setup(authenticated_client, monkeypatch)
    _create_connection(authenticated_client, "any-label-at-all")

    response = _contract(authenticated_client, _PRIVATE_ID)

    assert response.status_code == 200, response.text
    assert response.json()["model"]["upstream_id"] == _DISCOVERED, response.json()["model"]
    assert http.keys_seen == [_KEY], "the stored connection key funded the snapshot"


# ── refusals: the id exists only in the context that discovered it ────────────


def test_another_account_cannot_resolve_a_connection_discovered_id(
    authenticated_client: TestClient,
    provisioned_user_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(authenticated_client, monkeypatch)
    _create_connection(authenticated_client, "personal")
    assert _contract(authenticated_client, _PRIVATE_ID).status_code == 200

    provisioned_user_factory("account-b")
    token = authenticated_client.post(
        "/v1/auth/login", json={"username": "account-b", "password": "test-user-password"}
    ).json()["token"]

    as_b = _contract(
        authenticated_client, _PRIVATE_ID, headers={"Authorization": f"Bearer {token}"}
    )

    assert as_b.status_code == 404, as_b.text
    assert as_b.json()["detail"]["code"] == "model_not_found", as_b.json()


def test_two_active_connections_are_ambiguous_and_resolve_no_private_id(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: an ambiguous credential funds no admission — and no egress."""
    http = _setup(authenticated_client, monkeypatch)
    _create_connection(authenticated_client, "work", "sk-ant-work")
    _create_connection(authenticated_client, "personal", "sk-ant-personal")

    response = _contract(authenticated_client, _PRIVATE_ID)

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "model_not_found", response.json()
    assert http.keys_seen == [], "ambiguity never picked a key to dial with"


def test_a_default_label_does_not_admit_a_private_id_when_another_connection_is_active(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: the implicit request has no label-based ambiguity escape hatch."""
    http = _setup(authenticated_client, monkeypatch)
    _create_connection(authenticated_client, "default", "sk-ant-default")
    _create_connection(authenticated_client, "other", "sk-ant-other")

    response = _contract(authenticated_client, _PRIVATE_ID)

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "model_not_found", response.json()
    assert http.keys_seen == [], "ambiguity never picked the default-labelled key"


# ── the revision fence extends to Connection identity ─────────────────────────


def _replace_connection_key_at_the_seam(
    monkeypatch: pytest.MonkeyPatch, connection_id: str
) -> dict[str, int]:
    """Advance the Connection's durable credential generation EXACTLY at the seam.

    # WHY ``reactivate``: it is the same conditional UPDATE the api-key replacement
    # route commits — status back to active plus an atomic ``credential_generation``
    # bump — so this is a real key replacement as the fence sees one, driven on the
    # app's own loop between id admission and credential resolution.
    """
    real = model_parameters_module._credential_target_for_chat
    rotations = {"n": 0}

    async def _wrapper(request: Any, **kwargs: Any):
        if rotations["n"] == 0:
            rotations["n"] += 1
            store = OAuthConnectionStore()
            connection = await store.get(kwargs["account_id"], UUID(connection_id))
            assert connection is not None, "the barrier needs an existing connection"
            assert await store.reactivate(connection) is not None
        return await real(request, **kwargs)

    monkeypatch.setattr(model_parameters_module, "_credential_target_for_chat", _wrapper)
    return rotations


def test_a_connection_key_replacement_at_the_seam_is_refused(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(authenticated_client, monkeypatch)
    connection_id = _create_connection(authenticated_client, "personal")
    rotations = _replace_connection_key_at_the_seam(monkeypatch, connection_id)

    response = _contract(authenticated_client, _PRIVATE_ID)

    assert rotations["n"] == 1, "the barrier did not fire — the test proves nothing"
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "credential_generation_changed", detail
    assert _KEY not in response.text


def test_a_retry_after_the_connection_replacement_settles_resolves(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(authenticated_client, monkeypatch)
    connection_id = _create_connection(authenticated_client, "personal")
    rotations = _replace_connection_key_at_the_seam(monkeypatch, connection_id)
    assert _contract(authenticated_client, _PRIVATE_ID).status_code == 409

    retry = _contract(authenticated_client, _PRIVATE_ID)

    assert rotations["n"] == 1, "the barrier must not fire again"
    assert retry.status_code == 200, retry.text
    assert retry.json()["model"]["id"] == _PRIVATE_ID, retry.json()["model"]
