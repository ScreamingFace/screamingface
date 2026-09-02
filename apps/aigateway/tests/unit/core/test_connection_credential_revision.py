"""OME-1026 U2 — the durable revision fence for Connection-backed credentials.

FEATURE: local mode represents the effective provider credential as one active
``OAuthConnection``. Its private catalog snapshots are keyed by a NON-SECRET
durable revision, so replacing the stored key — which keeps the SAME connection
id (`PUT /v1/oauth/connections/{id}/api-key`) — retires every snapshot the old
credential produced, exactly as a hosted Profile's ``credential_generation``
does.

INVARIANT (the load-bearing one): a snapshot fetched under a replaced local
credential can never be READ under the replacement, and a stale in-flight
refresh started under the old credential can never publish rows the replacement
can read. Both hold structurally — the cache identity carries the durable
per-connection generation — not by remembering to invalidate.

INVARIANT (no wall-clock identity): ``last_refreshed_at`` moves on every
replacement too, but two replacements inside one clock tick would alias it
(the same defect OME-1026 F3 fixed for Profiles). The fence is a strictly
advancing integer bumped inside the SAME conditional UPDATE that publishes the
credential, so it is atomic under the row lock and unique across workers.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.core.effective_credential import (
    EffectiveCredential,
    resolve_effective_credential,
)
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.profile_model_catalog import ProfileModelCatalog
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings

_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_OLD_KEY = "sk-ant-old"
_NEW_KEY = "sk-ant-new"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _PerKeyCatalog:
    """A canned Anthropic catalog whose answer depends on the KEY that dialled."""

    def __init__(self, per_key: dict[str, list[str]]) -> None:
        self._per_key = per_key
        self.keys_seen: list[str] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert url == _FIRST_PAGE, f"unexpected dial: {url}"
        key = headers["x-api-key"]
        self.keys_seen.append(key)
        body = json.dumps(
            {
                "data": [{"id": model_id, "type": "model"} for model_id in self._per_key[key]],
                "has_more": False,
            }
        )
        return RawResponse(status=200, content_type="application/json", body=body)


class _GatedPerKeyCatalog(_PerKeyCatalog):
    """Blocks the FIRST dial until released — a stale in-flight refresh, on demand."""

    def __init__(self, per_key: dict[str, list[str]], gate: asyncio.Event) -> None:
        super().__init__(per_key)
        self._gate = gate
        self._first = True

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        if self._first:
            self._first = False
            await self._gate.wait()
        return await super().get(url, timeout_s=timeout_s, max_bytes=max_bytes, headers=headers)


def _portal(client: TestClient):
    portal = client.portal
    assert portal is not None, "the TestClient must be entered as a context manager"
    return portal


def _accept_any_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


def _configure(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> AnthropicPluginSettings:
    settings = AnthropicPluginSettings(**overrides)
    monkeypatch.setattr(anthropic_plugin_module.PLUGIN, "settings", settings)
    return settings


def _quiet_discovery(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.state.profile_model_catalog = None


def _account_id(client: TestClient) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _create_connection(client: TestClient, label: str, api_key: str) -> str:
    response = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "anthropic", "label": label, "api_key": api_key},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _replace_key(client: TestClient, connection_id: str, api_key: str) -> None:
    response = client.put(
        f"/v1/oauth/connections/{connection_id}/api-key", json={"api_key": api_key}
    )
    assert response.status_code == 200, response.text


def _resolve(client: TestClient) -> EffectiveCredential:
    app = cast(FastAPI, client.app)
    account_id = _account_id(client)

    async def _run() -> Any:
        return await resolve_effective_credential(
            account_id=account_id,
            provider="anthropic",
            profile_index=app.state.profile_index,
            connections=OAuthConnectionStore(),
        )

    resolution = _portal(client).call(_run)
    assert isinstance(resolution, EffectiveCredential), resolution
    return resolution


def _generation_of(client: TestClient, connection_id: str) -> int:
    account_id = _account_id(client)

    async def _run() -> int:
        row = await OAuthConnectionStore().get(account_id, connection_id)
        assert row is not None
        return row.credential_generation

    return _portal(client).call(_run)


def _auth_provider(key: str):
    from aigateway.core.model_discovery_scope import ProviderAuthContext

    async def _build() -> Any:
        return ProviderAuthContext(headers={"x-api-key": key}, auth_type="api_key")

    return _build


def _snapshot_for_target(
    client: TestClient,
    catalog: ProfileModelCatalog,
    target: EffectiveCredential,
    http: Any,
    *,
    wait_budget_s: float | None = None,
) -> Any:
    plugin = anthropic_plugin_module.PLUGIN
    key_for_dial = _OLD_KEY if target.credential_revision.endswith("gen1") else _NEW_KEY

    async def _run() -> Any:
        return await catalog.snapshot_for_target(
            plugin,
            account_id=target.account_id,
            target=target,
            client=http,
            limits=DiscoveryLimits(),
            auth_provider=_auth_provider(key_for_dial),
            wait_budget_s=wait_budget_s,
        )

    return _portal(client).call(_run)


# ── the durable generation ─────────────────────────────────────────────────────


def test_creating_an_api_key_connection_publishes_generation_one(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    connection_id = _create_connection(authenticated_client, "personal", _OLD_KEY)

    assert _generation_of(authenticated_client, connection_id) == 1


def test_replacing_the_api_key_bumps_the_durable_generation(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    connection_id = _create_connection(authenticated_client, "personal", _OLD_KEY)

    _replace_key(authenticated_client, connection_id, _NEW_KEY)
    assert _generation_of(authenticated_client, connection_id) == 2

    _replace_key(authenticated_client, connection_id, "sk-ant-newer")
    assert _generation_of(authenticated_client, connection_id) == 3


def test_replacement_changes_the_effective_cache_revision(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    connection_id = _create_connection(authenticated_client, "personal", _OLD_KEY)
    before = _resolve(authenticated_client).credential_revision

    _replace_key(authenticated_client, connection_id, _NEW_KEY)
    after = _resolve(authenticated_client).credential_revision

    assert before != after
    assert _OLD_KEY not in before + after and _NEW_KEY not in before + after


def test_delete_and_recreate_never_reuse_a_cache_identity(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    connection_id = _create_connection(authenticated_client, "personal", _OLD_KEY)
    before = _resolve(authenticated_client).credential_revision

    deleted = authenticated_client.delete(f"/v1/oauth/connections/{connection_id}")
    assert deleted.status_code == 204
    _create_connection(authenticated_client, "personal", _NEW_KEY)
    after = _resolve(authenticated_client).credential_revision

    assert before != after


def test_an_errored_connection_stops_resolving(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _quiet_discovery(authenticated_client)
    connection_id = _create_connection(authenticated_client, "personal", _OLD_KEY)
    app = cast(FastAPI, authenticated_client.app)
    account_id = _account_id(authenticated_client)

    async def _mark_error() -> None:
        store = OAuthConnectionStore()
        row = await store.get(account_id, connection_id)
        assert row is not None
        assert await store.mark_error(row, "credential rejected") is not None

    _portal(authenticated_client).call(_mark_error)

    async def _run() -> Any:
        return await resolve_effective_credential(
            account_id=account_id,
            provider="anthropic",
            profile_index=app.state.profile_index,
            connections=OAuthConnectionStore(),
        )

    assert _portal(authenticated_client).call(_run) is None


# ── the catalog fence ──────────────────────────────────────────────────────────


def test_a_replaced_credential_cannot_read_the_previous_snapshot(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _configure(monkeypatch)
    _quiet_discovery(authenticated_client)
    connection_id = _create_connection(authenticated_client, "personal", _OLD_KEY)
    http = _PerKeyCatalog({_OLD_KEY: ["claude-old-entitlement"], _NEW_KEY: ["claude-new"]})
    catalog = ProfileModelCatalog(clock=_Clock(), max_identities=8, max_inflight_refreshes=8)

    try:
        old_target = _resolve(authenticated_client)
        first = _snapshot_for_target(authenticated_client, catalog, old_target, http)
        assert first.status == "fresh"
        assert [e.model_name for e in first.entries] == ["claude-old-entitlement"]
        assert http.keys_seen == [_OLD_KEY]

        _replace_key(authenticated_client, connection_id, _NEW_KEY)
        new_target = _resolve(authenticated_client)

        second = _snapshot_for_target(authenticated_client, catalog, new_target, http)
        # The replacement NEVER reads the old snapshot: it dials with its own key
        # and sees only what that key can call.
        assert http.keys_seen == [_OLD_KEY, _NEW_KEY]
        assert second.status == "fresh"
        assert [e.model_name for e in second.entries] == ["claude-new"]
    finally:
        _portal(authenticated_client).call(catalog.aclose)


def test_a_stale_inflight_refresh_publishes_only_under_its_own_identity(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refresh that lost the replacement race lands under the OLD identity.

    # WHY events and a zero wait rather than sleeps: the refresh must be provably
    # in flight when the replacement commits, and provably finished before the
    # replacement reads — both are barriers, not durations.
    """
    _accept_any_api_key(monkeypatch)
    _configure(monkeypatch)
    _quiet_discovery(authenticated_client)
    connection_id = _create_connection(authenticated_client, "personal", _OLD_KEY)
    gate = _portal(authenticated_client).call(asyncio.Event)
    http = _GatedPerKeyCatalog(
        {_OLD_KEY: ["claude-old-entitlement"], _NEW_KEY: ["claude-new"]}, gate
    )
    catalog = ProfileModelCatalog(clock=_Clock(), max_identities=8, max_inflight_refreshes=8)

    try:
        old_target = _resolve(authenticated_client)
        started = _snapshot_for_target(
            authenticated_client, catalog, old_target, http, wait_budget_s=0.0
        )
        assert started.status == "refreshing", "the stale refresh is provably in flight"

        _replace_key(authenticated_client, connection_id, _NEW_KEY)
        new_target = _resolve(authenticated_client)

        _portal(authenticated_client).call(gate.set)
        _portal(authenticated_client).call(catalog.drain)

        replacement = _snapshot_for_target(authenticated_client, catalog, new_target, http)
        assert replacement.status == "fresh"
        assert [e.model_name for e in replacement.entries] == ["claude-new"]
        assert http.keys_seen == [_OLD_KEY, _NEW_KEY], (
            "the replacement dialed for itself instead of reading the stale publication"
        )
    finally:
        _portal(authenticated_client).call(catalog.aclose)


def test_replacing_the_key_retires_the_inflight_refresh_promptly(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route-level lifecycle hook, mirroring the Profile publication path.

    # WHY on top of the identity fence: the fence already makes the stale snapshot
    # unreadable; this cancels the doomed in-flight dial so a REPLACED key spends no
    # further upstream request, and the memory is released promptly instead of by LRU.
    """
    _accept_any_api_key(monkeypatch)
    _configure(monkeypatch)
    connection_id = _create_connection(authenticated_client, "personal", _OLD_KEY)
    gate = _portal(authenticated_client).call(asyncio.Event)
    http = _GatedPerKeyCatalog(
        {_OLD_KEY: ["claude-old-entitlement"], _NEW_KEY: ["claude-new"]}, gate
    )
    catalog = ProfileModelCatalog(clock=_Clock(), max_identities=8, max_inflight_refreshes=8)
    app = cast(FastAPI, authenticated_client.app)
    app.state.profile_model_catalog = catalog

    try:
        old_target = _resolve(authenticated_client)
        started = _snapshot_for_target(
            authenticated_client, catalog, old_target, http, wait_budget_s=0.0
        )
        assert started.status == "refreshing"
        assert catalog.inflight_refreshes == 1

        _replace_key(authenticated_client, connection_id, _NEW_KEY)

        # Deterministic discriminator: the gate opens only AFTER the replacement
        # committed. A refresh the hook cancelled ends at the gate and never dials;
        # an uncancelled one would proceed and record the OLD key.
        _portal(authenticated_client).call(gate.set)
        _portal(authenticated_client).call(catalog.drain)
        assert catalog.inflight_refreshes == 0
        assert http.keys_seen == [], (
            "the superseded refresh was cancelled before it could dial with the old key"
        )
    finally:
        _portal(authenticated_client).call(catalog.aclose)


def test_deleting_the_connection_retires_the_inflight_refresh_promptly(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)
    _configure(monkeypatch)
    connection_id = _create_connection(authenticated_client, "personal", _OLD_KEY)
    gate = _portal(authenticated_client).call(asyncio.Event)
    http = _GatedPerKeyCatalog({_OLD_KEY: ["claude-old-entitlement"]}, gate)
    catalog = ProfileModelCatalog(clock=_Clock(), max_identities=8, max_inflight_refreshes=8)
    app = cast(FastAPI, authenticated_client.app)
    app.state.profile_model_catalog = catalog

    try:
        old_target = _resolve(authenticated_client)
        started = _snapshot_for_target(
            authenticated_client, catalog, old_target, http, wait_budget_s=0.0
        )
        assert started.status == "refreshing"

        deleted = authenticated_client.delete(f"/v1/oauth/connections/{connection_id}")
        assert deleted.status_code == 204

        _portal(authenticated_client).call(gate.set)
        _portal(authenticated_client).call(catalog.drain)
        assert catalog.inflight_refreshes == 0
        assert http.keys_seen == [], (
            "the deleted connection's refresh was cancelled before it could dial"
        )
    finally:
        _portal(authenticated_client).call(catalog.aclose)
