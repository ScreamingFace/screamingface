"""OME-1026 adversarial B2 (F4) — every real ownership change retires the private identity.

FEATURE: a private model listing, and the profile-bound contract built from it, that
belongs to ONE credential owner.

STORY: as an owner who replaces a profile's credential, the models the PREVIOUS
credential could see stop resolving for me — the new key's entitlements are what my
listing and my contracts describe.

INVARIANT (the fence): the private cache identity is
``(account_id, provider, profile_name, "{auth_type}@gen{N}")``. ``N`` is the durable
ownership generation, bumped inside the profile-index CAS by every publication that
replaces the credential's owner: key replacement, OAuth re-authentication, auth-type
switch, and delete/recreate (which never rewinds it). A routine same-owner token refresh
is deliberately NOT such an event (owner decision 6) and is proved elsewhere.

INVARIANT (auth type is in the identity too): so an owner/auth change cannot be accepted
at the SAME generation. That is free defence in depth — a switch bumps the generation as
well — and it is what makes a mismatched pair unable to alias even if a future
publication path forgot to bump.
"""

from __future__ import annotations

import json
from typing import Any, cast

import httpx
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
from aigateway.core.plugin_base import ModelDiscoverySource
from aigateway.core.profile_models import AuthType, Profile, ProfileState, profile_id_for
from aigateway.core.profile_snapshot_store import (
    ProfileCacheKey,
    ProfileSnapshotStore,
    profile_credential_revision,
)
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from tests.conftest import drain_private_catalog

_NAME = "work"
_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_PARAMS_URL = "/v1/model-parameters"
_LISTING_URL = f"/v1/auth/anthropic/profiles/{_NAME}/models"
_PROFILE_URL = f"/v1/auth/anthropic/profiles/{_NAME}"
_API_KEY_URL = f"/v1/auth/anthropic/profiles/{_NAME}/api-key"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _PerOwnerCatalog:
    """A canned private catalog that returns a DIFFERENT model per credential owner.

    # WHY per-owner ids: if every dial returned the same list, a test asserting "the old
    # id no longer resolves" would pass for the wrong reason the moment the new owner's
    # post-commit discovery re-published the same id. Distinct ids make the assertion
    # mean "the PREVIOUS owner's entitlement is gone", which is the actual guarantee.
    """

    def __init__(self) -> None:
        self.dials = 0

    @property
    def current_id(self) -> str:
        return f"claude-owner-{self.dials}-only"

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert headers is not None, "the private catalog must be dialed WITH a credential"
        assert url == _FIRST_PAGE, url
        self.dials += 1
        body = json.dumps({"data": [{"id": self.current_id, "type": "model"}], "has_more": False})
        return RawResponse(status=200, content_type="application/json", body=body)


def _token_factory(token: str):
    async def token_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "refresh_token": f"refresh-{token}",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(token_handler), timeout=httpx.Timeout(5.0)
    )


def _setup(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> _PerOwnerCatalog:
    monkeypatch.setattr(
        anthropic_plugin_module.PLUGIN, "settings", AnthropicPluginSettings(live_models=True)
    )

    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)
    http = _PerOwnerCatalog()
    cast(FastAPI, client.app).state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    return http


def _store_a_key(client: TestClient, key: str) -> None:
    response = client.put(_API_KEY_URL, json={"api_key": key})
    assert response.status_code == 200, response.text


def _first_owners_private_id(client: TestClient, http: _PerOwnerCatalog) -> str:
    """Publish owner A's key, let discovery land, and return the id only A can see."""
    _store_a_key(client, "sk-ant-owner-a-0000AAAA")
    drain_private_catalog(client)
    listing = client.get(_LISTING_URL)
    assert listing.status_code == 200, listing.text
    assert listing.json()["status"] == "fresh", listing.json()
    owner_a_id = f"anthropic/{http.current_id}"
    seeds = {entry.model_name for entry in anthropic_plugin_module.PLUGIN.register_models()}
    assert http.current_id not in seeds, "the premise is an id ONLY the snapshot has"
    return owner_a_id


def _contract(client: TestClient, model: str):
    return client.get(_PARAMS_URL, params={"model": model}, headers={"X-Profile": _NAME})


# ── each real ownership change retires the previous owner's identity ───────────


def test_a_key_replacement_retires_the_previous_owners_private_contract(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner decision 7: an actual key replacement IS an ownership change."""
    http = _setup(authenticated_client, monkeypatch)
    owner_a_id = _first_owners_private_id(authenticated_client, http)
    assert _contract(authenticated_client, owner_a_id).status_code == 200

    _store_a_key(authenticated_client, "sk-ant-owner-b-0000BBBB")
    drain_private_catalog(authenticated_client)

    refused = _contract(authenticated_client, owner_a_id)
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"]["code"] == "model_not_found", refused.json()
    # The NEW owner's own entitlement resolves, so the refusal is about ownership and
    # not about private discovery having stopped working.
    assert _contract(authenticated_client, f"anthropic/{http.current_id}").status_code == 200


def test_an_oauth_reauthentication_retires_the_previous_owners_private_contract(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh OAuth login for the same profile is a new credential owner."""
    http = _setup(authenticated_client, monkeypatch)
    owner_a_id = _first_owners_private_id(authenticated_client, http)
    assert _contract(authenticated_client, owner_a_id).status_code == 200

    app = cast(FastAPI, authenticated_client.app)
    app.state.anthropic_http_factory = _token_factory("oauth-owner-b")
    start = authenticated_client.post("/v1/auth/anthropic/profiles", json={"name": _NAME})
    assert start.status_code == 201, start.text
    callback = authenticated_client.get(
        "/v1/auth/anthropic/callback",
        params={"code": "code-B", "state": start.json()["state"]},
        follow_redirects=False,
    )
    assert callback.status_code == 200, callback.text
    drain_private_catalog(authenticated_client)

    refused = _contract(authenticated_client, owner_a_id)
    assert refused.status_code == 404, refused.text


def test_an_auth_type_switch_retires_the_previous_owners_private_contract(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """api_key -> oauth on the same profile: a different credential entirely.

    # WHY this direction: Anthropic refuses private discovery for OAuth outright
    # (``unsupported_auth_type`` — a Claude-subscription token is not known to work with
    # the Models API and must not spend a credentialed request finding out). So the
    # oauth->api_key direction has no PREVIOUS snapshot to leak, and this direction is
    # the one where the switch has something to retire.
    """
    http = _setup(authenticated_client, monkeypatch)
    owner_a_id = _first_owners_private_id(authenticated_client, http)
    assert _contract(authenticated_client, owner_a_id).status_code == 200

    app = cast(FastAPI, authenticated_client.app)
    app.state.anthropic_http_factory = _token_factory("oauth-owner-b")
    start = authenticated_client.post("/v1/auth/anthropic/profiles", json={"name": _NAME})
    assert start.status_code == 201, start.text
    assert (
        authenticated_client.get(
            "/v1/auth/anthropic/callback",
            params={"code": "code-B", "state": start.json()["state"]},
            follow_redirects=False,
        ).status_code
        == 200
    )
    drain_private_catalog(authenticated_client)

    refused = _contract(authenticated_client, owner_a_id)
    assert refused.status_code == 404, refused.text
    listing = authenticated_client.get(_LISTING_URL)
    assert listing.json()["reason"] == "unsupported_auth_type", listing.json()
    served = {row["id"] for row in listing.json()["data"]}
    assert owner_a_id not in served, "the api-key owner's rows were served to the OAuth profile"


def test_delete_and_recreate_cannot_reach_the_previous_owners_snapshot(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The generation is never rewound, so a recreated name is a NEW identity."""
    http = _setup(authenticated_client, monkeypatch)
    owner_a_id = _first_owners_private_id(authenticated_client, http)
    assert _contract(authenticated_client, owner_a_id).status_code == 200

    assert authenticated_client.delete(_PROFILE_URL).status_code == 204
    _store_a_key(authenticated_client, "sk-ant-recreated-0000DDDD")
    drain_private_catalog(authenticated_client)

    refused = _contract(authenticated_client, owner_a_id)
    assert refused.status_code == 404, refused.text
    assert _contract(authenticated_client, f"anthropic/{http.current_id}").status_code == 200


# ── the same generation is not enough to be the same owner ────────────────────


def _profile(auth_type: AuthType) -> Profile:
    return Profile(
        id=profile_id_for("acct", "anthropic", _NAME),
        account_id="acct",
        provider="anthropic",
        name=_NAME,
        state=ProfileState.AUTHENTICATED,
        auth_type=auth_type,
    )


def test_the_private_revision_distinguishes_auth_types_at_one_generation() -> None:
    """An owner/auth change at the SAME generation still changes the identity."""
    api_key = profile_credential_revision(_profile("api_key"), 2)
    oauth = profile_credential_revision(_profile("oauth"), 2)

    assert api_key != oauth, (api_key, oauth)
    assert api_key == "api_key@gen2" and oauth == "oauth@gen2"


def test_a_snapshot_stored_under_one_auth_type_is_unreadable_under_another() -> None:
    """The store keys on the whole tuple, so the two identities cannot alias.

    # WHY assert this at the store: it is the layer that decides what may be SERVED. A
    # route-level check can be forgotten; an identity that cannot be looked up cannot be
    # served by any caller, including one written next year.
    """
    source = ModelDiscoverySource(
        key="anthropic:models", revision="test", ttl_s=60.0, stale_ttl_s=60.0, failure_ttl_s=0.0
    )
    store = ProfileSnapshotStore(clock=_Clock(), max_identities=8)
    api_key_identity: ProfileCacheKey = (
        "acct",
        "anthropic",
        _NAME,
        profile_credential_revision(_profile("api_key"), 2),
    )
    oauth_identity: ProfileCacheKey = (
        "acct",
        "anthropic",
        _NAME,
        profile_credential_revision(_profile("oauth"), 2),
    )
    store.store(api_key_identity, (object(),))  # type: ignore[arg-type]

    offline, stale = store.offline_answer(oauth_identity, source=source)

    assert offline is None, "the other auth type's snapshot was offered as an answer"
    assert stale is None
    assert store.offline_answer(api_key_identity, source=source)[0] is not None
