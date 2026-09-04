"""OME-1026 rework U5 — ``GET /v1/auth/{provider}/profiles/{name}/models``.

FEATURE: the private model list. A profile owner asks what their OWN stored
credential can call, and gets a live answer without re-entering the key.

STORY: as an account owner who stored an Anthropic API key, I open my profile and
see the models that key may call — labelled fresh/stale/refreshing so I know
whether I am looking at live data — and no one else can see that list.

INVARIANT (asserted from the HTTP boundary, which is where it matters): the
listing is resolved from the CALLER's account. Another account asking for the same
profile name gets its own answer or a 404 — never these rows.
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
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings

_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_A_KEY = "sk-ant-account-a-key"
_B_KEY = "sk-ant-account-b-key"
_URL = "/v1/auth/anthropic/profiles/{name}/models"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _CatalogClient:
    """A canned Anthropic catalog whose answer depends on the KEY that dialled.

    # WHY key-dependent: that is the real upstream's behaviour — ``GET /v1/models``
    # answers for the calling credential — and it is what makes a cross-account leak
    # visible in a test instead of invisible.
    """

    def __init__(self, per_key: dict[str, list[str]] | None = None, *, status: int = 200) -> None:
        self._per_key = per_key or {_A_KEY: ["claude-a-only"], _B_KEY: ["claude-b-only"]}
        self._status = status
        self.dialed: list[str] = []
        self.keys_seen: list[str] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        self.dialed.append(url)
        assert headers is not None, "a private catalog dial must carry the profile's credential"
        assert "authorization" not in {name.lower() for name in headers}, (
            "a raw key must travel as x-api-key, never as a bearer token"
        )
        key = headers["x-api-key"]
        self.keys_seen.append(key)
        if url != _FIRST_PAGE:
            raise AssertionError(f"unexpected dial: {url}")
        if self._status != 200:
            return RawResponse(
                status=self._status,
                content_type="application/json",
                body=json.dumps({"type": "error"}),
            )
        body = json.dumps(
            {
                "data": [{"id": model_id, "type": "model"} for model_id in self._per_key[key]],
                "has_more": False,
            }
        )
        return RawResponse(status=200, content_type="application/json", body=body)


class _LoudClient:
    def __init__(self) -> None:
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None) -> Any:
        self.dialed.append(url)
        raise AssertionError(f"forbidden discovery egress: {url}")


def _configure(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> AnthropicPluginSettings:
    settings = AnthropicPluginSettings(**overrides)
    monkeypatch.setattr(anthropic_plugin_module.PLUGIN, "settings", settings)
    return settings


def _install(client: TestClient, http: Any) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )


def _accept_any_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


def _store_key(client: TestClient, name: str, api_key: str) -> None:
    response = client.put(f"/v1/auth/anthropic/profiles/{name}/api-key", json={"api_key": api_key})
    assert response.status_code == 200, response.text


def _ids(payload: dict) -> list[str]:
    return [row["id"] for row in payload["data"]]


def _seed_ids(settings: AnthropicPluginSettings) -> list[str]:
    return [f"anthropic/{entry.model_name}" for entry in settings.models]


async def _put_profile(
    client: TestClient,
    credential_blobs: Any,
    *,
    name: str,
    state: ProfileState = ProfileState.AUTHENTICATED,
    auth_type: str = "api_key",
) -> None:
    account_id = client.get("/v1/auth/me").json()["id"]
    await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", name),
            account_id=account_id,
            provider="anthropic",
            name=name,
            state=state,
            auth_type=auth_type,  # type: ignore[arg-type]
        )
    )


# ── resolution and ownership ──────────────────────────────────────────────────


def test_an_unknown_provider_is_a_404(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/v1/auth/nope/profiles/work/models")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_provider"


def test_a_missing_profile_is_a_404(authenticated_client: TestClient) -> None:
    response = authenticated_client.get(_URL.format(name="never-created"))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "profile_not_found"


def test_another_account_cannot_read_this_profiles_models(
    authenticated_client: TestClient,
    provisioned_user_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT (the confirmation the owner asked for, at the HTTP boundary).

    # WHY 404 and not 403: the profile is resolved from the CALLER's account, so for
    # account B the name simply does not exist. There is no lookup that could reach
    # A's row, which is a stronger property than an authorization check on one.
    """
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CatalogClient()
    _install(authenticated_client, http)
    _store_key(authenticated_client, "work", _A_KEY)

    a_models = authenticated_client.get(_URL.format(name="work")).json()
    assert _ids(a_models) == ["anthropic/claude-a-only"]

    provisioned_user_factory("account-b")
    token = authenticated_client.post(
        "/v1/auth/login", json={"username": "account-b", "password": "test-user-password"}
    ).json()["token"]

    as_b = authenticated_client.get(
        _URL.format(name="work"), headers={"Authorization": f"Bearer {token}"}
    )

    assert as_b.status_code == 404, "account B has no profile called 'work'"
    assert http.keys_seen == [_A_KEY], "and B's request funded no dial with A's key"


def test_two_accounts_with_the_same_profile_name_get_their_own_models(
    authenticated_client: TestClient,
    provisioned_user_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CatalogClient()
    _install(authenticated_client, http)
    _store_key(authenticated_client, "work", _A_KEY)
    a_token = authenticated_client.headers["Authorization"]

    provisioned_user_factory("account-b")
    b_token = authenticated_client.post(
        "/v1/auth/login", json={"username": "account-b", "password": "test-user-password"}
    ).json()["token"]
    authenticated_client.headers.update({"Authorization": f"Bearer {b_token}"})
    _store_key(authenticated_client, "work", _B_KEY)

    b_models = authenticated_client.get(_URL.format(name="work")).json()
    authenticated_client.headers.update({"Authorization": a_token})
    a_models = authenticated_client.get(_URL.format(name="work")).json()

    assert _ids(b_models) == ["anthropic/claude-b-only"]
    assert _ids(a_models) == ["anthropic/claude-a-only"], "A's list is unchanged by B"
    assert sorted(http.keys_seen) == sorted([_A_KEY, _B_KEY])


# ── the live answer ───────────────────────────────────────────────────────────


def test_a_stored_key_produces_a_fresh_private_listing_without_re_entry(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CatalogClient()
    _install(authenticated_client, http)
    _store_key(authenticated_client, "work", _A_KEY)

    payload = authenticated_client.get(_URL.format(name="work")).json()

    assert payload["provider"] == "anthropic"
    assert payload["profile"] == "work"
    assert payload["status"] == "fresh"
    assert payload["reason"] is None
    assert _ids(payload) == ["anthropic/claude-a-only"]
    # The credential came from the encrypted store, not from this request.
    assert http.keys_seen == [_A_KEY]


def test_the_rows_keep_the_public_listing_shape_and_leak_no_credential(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    _store_key(authenticated_client, "work", _A_KEY)

    response = authenticated_client.get(_URL.format(name="work"))
    row = response.json()["data"][0]

    assert row["object"] == "model"
    assert row["owned_by"] == "anthropic"
    assert "supported_parameters" in row and "unsupported_parameter_behavior" in row
    assert _A_KEY not in response.text
    assert "x-api-key" not in response.text


def test_a_second_request_is_served_from_cache_with_one_upstream_dial(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CatalogClient()
    _install(authenticated_client, http)
    _store_key(authenticated_client, "work", _A_KEY)

    first = authenticated_client.get(_URL.format(name="work")).json()
    second = authenticated_client.get(_URL.format(name="work")).json()

    assert (first["status"], second["status"]) == ("fresh", "fresh")
    assert len(http.dialed) == 1, "the model picker may poll; the upstream must not"


def test_storing_the_key_triggers_discovery_before_the_first_models_request(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURE: the list is warm by the time the owner looks at it.

    # WHY the PUT does not wait for it: publishing a credential must not inherit the
    # upstream catalog's latency or its failures. The refresh is started post-commit
    # and the response returns immediately.
    """
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CatalogClient()
    _install(authenticated_client, http)

    _store_key(authenticated_client, "work", _A_KEY)
    payload = authenticated_client.get(_URL.format(name="work")).json()

    assert payload["status"] == "fresh"
    # Whether the GET found the snapshot or joined the in-flight refresh, exactly one
    # upstream attempt was made for this credential generation.
    assert len(http.dialed) == 1


def test_replacing_the_key_retires_the_previous_listing(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: a listing belongs to ONE credential generation."""
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CatalogClient({_A_KEY: ["claude-a-only"], _B_KEY: ["claude-rotated"]})
    _install(authenticated_client, http)
    _store_key(authenticated_client, "work", _A_KEY)

    before = authenticated_client.get(_URL.format(name="work")).json()
    _store_key(authenticated_client, "work", _B_KEY)
    after = authenticated_client.get(_URL.format(name="work")).json()

    assert _ids(before) == ["anthropic/claude-a-only"]
    assert _ids(after) == ["anthropic/claude-rotated"], "the old snapshot is not served"


def test_deleting_the_profile_removes_its_private_listing(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    _store_key(authenticated_client, "work", _A_KEY)
    authenticated_client.get(_URL.format(name="work"))

    app = cast(FastAPI, authenticated_client.app)
    assert app.state.profile_model_catalog.tracked_identities == 1

    assert authenticated_client.delete("/v1/auth/anthropic/profiles/work").status_code == 204

    assert app.state.profile_model_catalog.tracked_identities == 0, "no orphaned snapshot"
    assert authenticated_client.get(_URL.format(name="work")).status_code == 404


# ── refusals: 200 with seeds and a reason, and zero egress ────────────────────


@pytest.mark.asyncio
async def test_an_oauth_profile_is_refused_with_seeds_and_zero_egress(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, credential_blobs: Any
) -> None:
    settings = _configure(monkeypatch)
    http = _LoudClient()
    _install(authenticated_client, http)
    await _put_profile(authenticated_client, credential_blobs, name="sub", auth_type="oauth")

    payload = authenticated_client.get(_URL.format(name="sub")).json()

    assert payload["status"] == "fallback"
    assert payload["reason"] == "unsupported_auth_type"
    assert _ids(payload) == _seed_ids(settings), "the picker still shows the compiled catalog"
    assert http.dialed == []


@pytest.mark.asyncio
async def test_a_pending_profile_is_refused_with_zero_egress(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, credential_blobs: Any
) -> None:
    settings = _configure(monkeypatch)
    http = _LoudClient()
    _install(authenticated_client, http)
    await _put_profile(
        authenticated_client, credential_blobs, name="half-done", state=ProfileState.PENDING
    )

    payload = authenticated_client.get(_URL.format(name="half-done")).json()

    assert (payload["status"], payload["reason"]) == ("fallback", "profile_not_authenticated")
    assert _ids(payload) == _seed_ids(settings)
    assert http.dialed == []


def test_live_models_off_refuses_with_seeds_and_zero_egress(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch, live_models=False)
    _accept_any_api_key(monkeypatch)
    http = _LoudClient()
    _install(authenticated_client, http)
    _store_key(authenticated_client, "work", _A_KEY)

    payload = authenticated_client.get(_URL.format(name="work")).json()

    assert (payload["status"], payload["reason"]) == ("fallback", "discovery_disabled")
    assert _ids(payload) == _seed_ids(settings)
    assert http.dialed == []


def test_the_discovery_kill_switch_refuses_with_seeds_and_zero_egress(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``AIGW_DISCOVERY_ENABLED=false`` audits to zero discovery egress of any kind.

    # WHY the switch is flipped BEFORE the key is stored: publishing an api key starts
    # discovery post-commit, so a switch flipped afterwards would be measuring a
    # request that had already been allowed to dial.
    """
    settings = _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _LoudClient()
    _install(authenticated_client, http)
    app = cast(FastAPI, authenticated_client.app)
    app.state.profile_model_catalog = None  # the shape the builder returns when disabled
    _store_key(authenticated_client, "work", _A_KEY)

    payload = authenticated_client.get(_URL.format(name="work")).json()

    assert (payload["status"], payload["reason"]) == ("fallback", "discovery_disabled")
    assert _ids(payload) == _seed_ids(settings)
    assert http.dialed == []


def test_a_rejected_key_degrades_the_listing_and_not_the_route(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 401 from upstream is the owner's key problem — reported, not raised.

    # WHY 200 with a reason: the endpoint's job is to describe the listing. Turning an
    # upstream auth failure into a 5xx would make a UI that polls this endpoint look
    # broken, and would hide the compiled catalog the owner can still use.
    """
    settings = _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CatalogClient(status=401)
    _install(authenticated_client, http)
    _store_key(authenticated_client, "work", _A_KEY)

    response = authenticated_client.get(_URL.format(name="work"))
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "fallback"
    assert payload["reason"] == "bad_status"
    assert _ids(payload) == _seed_ids(settings)
    assert _A_KEY not in response.text
