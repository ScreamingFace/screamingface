"""OME-1026 U3 — ``GET /v1/models`` observes the caller's ONE effective credential.

FEATURE: implicit live model discovery. The Python Client calls ``sf.models.list()``
with no profile selection, so ``/v1/models`` resolves each provider's effective
credential for the CALLER — hosted: the Profile named ``default``; local: the sole
active Connection, whatever its label — and lists that credential's live models.

STORY: as a user with one stored Anthropic key, ``sf.models.list()`` shows me the
models MY key may call, in hosted and local deployments alike, without naming a
profile — and nobody else's listing ever shows them.

INVARIANT (the boundary that replaced the global exclusion): a credential-derived
row may appear ONLY in its own account's response. It never enters the
deployment-global ``ModelCatalog`` and never another account's response. Every
non-resolving outcome — no credential, unsupported auth type, ambiguous local
connections, a non-``default`` hosted profile — serves the compiled seeds
byte-identically, with ZERO provider egress.
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
from aigateway.core.model_capabilities import model_row
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.plugin_base import ModelEntry
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.live_models import LIVE_MODELS_URL
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings
from tests.conftest import drain_private_catalog

_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_A_KEY = "sk-ant-account-a-key"
_B_KEY = "sk-ant-account-b-key"
_PER_KEY = {_A_KEY: ["claude-a-only"], _B_KEY: ["claude-b-only"]}


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _CombinedClient:
    """One canned upstream for BOTH discovery scopes.

    Anthropic's private page answers per-KEY (the real upstream's behaviour — that
    is what makes a cross-account leak visible); OpenRouter's public page carries no
    credential at all, and this asserts it.
    """

    def __init__(
        self,
        per_key: dict[str, list[str]] | None = None,
        *,
        openrouter_ids: list[str] | None = None,
    ) -> None:
        self._per_key = per_key or dict(_PER_KEY)
        self._openrouter_ids = openrouter_ids or []
        self.dialed: list[str] = []
        self.keys_seen: list[str] = []
        self.openrouter_dials = 0

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        self.dialed.append(url)
        if url == LIVE_MODELS_URL:
            assert headers is None, "a PUBLIC catalog dial must carry no credential"
            self.openrouter_dials += 1
            rows = self._openrouter_ids
            envelope = {"data": [{"id": i} for i in rows], "links": {"next": None}}
            body = json.dumps({**envelope, "total_count": len(rows)})
            return RawResponse(status=200, content_type="application/json", body=body)
        assert url == _FIRST_PAGE, f"unexpected dial: {url}"
        assert headers is not None, "a private catalog dial must carry the credential"
        key = headers["x-api-key"]
        self.keys_seen.append(key)
        body = json.dumps(
            {"data": [{"id": m, "type": "model"} for m in self._per_key[key]], "has_more": False}
        )
        return RawResponse(status=200, content_type="application/json", body=body)


class _LoudClient:
    """Any catalog dial at all is the failure being asserted."""

    def __init__(self) -> None:
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None) -> Any:
        self.dialed.append(url)
        raise AssertionError(f"forbidden discovery egress: {url}")


def _portal(client: TestClient):
    portal = client.portal
    assert portal is not None, "the TestClient must be entered as a context manager"
    return portal


def _configure(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> AnthropicPluginSettings:
    settings = AnthropicPluginSettings(**overrides)
    monkeypatch.setattr(anthropic_plugin_module.PLUGIN, "settings", settings)
    return settings


def _enable_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )


def _install(client: TestClient, http: Any) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    app.state.model_catalog = ModelCatalog(clock=_Clock())


def _accept_any_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


def _store_key(client: TestClient, name: str, api_key: str, **request_kwargs: Any) -> None:
    response = client.put(
        f"/v1/auth/anthropic/profiles/{name}/api-key", json={"api_key": api_key}, **request_kwargs
    )
    assert response.status_code == 200, response.text


def _create_connection(client: TestClient, label: str, api_key: str) -> str:
    response = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "anthropic", "label": label, "api_key": api_key},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _put_oauth_profile(client: TestClient) -> None:
    """An AUTHENTICATED profile whose auth type has no discovery support."""
    app = cast(FastAPI, client.app)
    account_id = client.get("/v1/auth/me").json()["id"]
    profile = Profile(
        id=profile_id_for(account_id, "anthropic", "default"),
        account_id=account_id,
        provider="anthropic",
        name="default",
        state=ProfileState.AUTHENTICATED,
        auth_type="oauth",
    )
    _portal(client).call(app.state.profile_index.upsert, profile)


def _rows(client: TestClient, **request_kwargs: Any) -> list[dict]:
    response = client.get("/v1/models", **request_kwargs)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _anthropic_ids(client: TestClient, **request_kwargs: Any) -> list[str]:
    return [r["id"] for r in _rows(client, **request_kwargs) if r["owned_by"] == "anthropic"]


def _seed_ids(settings: AnthropicPluginSettings) -> list[str]:
    return [f"anthropic/{entry.model_name}" for entry in settings.models]


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/v1/auth/login", json={"username": username, "password": "test-user-password"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


# ── the effective credential goes live ────────────────────────────────────────


def test_a_hosted_default_profile_makes_v1_models_live_for_its_caller(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hosted mode: the Profile named ``default`` is the effective credential."""
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CombinedClient()
    _install(authenticated_client, http)
    _store_key(authenticated_client, "default", _A_KEY)

    assert _anthropic_ids(authenticated_client) == ["anthropic/claude-a-only"]
    # ONE dial: the publication warm; the listing itself is served from the private
    # snapshot (single-flight dedup), never by a second decrypt-and-dial.
    assert http.keys_seen == [_A_KEY]


def test_a_sole_active_connection_makes_v1_models_live_whatever_its_label(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local mode: the ONE active Connection is the effective credential."""
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CombinedClient(per_key={_A_KEY: ["claude-conn-only"]})
    _install(authenticated_client, http)
    _create_connection(authenticated_client, "any-label-at-all", _A_KEY)

    assert _anthropic_ids(authenticated_client) == ["anthropic/claude-conn-only"]
    assert http.keys_seen == [_A_KEY], "the stored connection key funded the dial"


def test_a_replaced_connection_key_relists_under_the_new_credential(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacing the key retires the old listing: the next response is the NEW key's."""
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CombinedClient(per_key={_A_KEY: ["claude-old-key"], _B_KEY: ["claude-new-key"]})
    _install(authenticated_client, http)
    connection_id = _create_connection(authenticated_client, "personal", _A_KEY)
    assert _anthropic_ids(authenticated_client) == ["anthropic/claude-old-key"]

    response = authenticated_client.put(
        f"/v1/oauth/connections/{connection_id}/api-key", json={"api_key": _B_KEY}
    )
    assert response.status_code == 200, response.text

    assert _anthropic_ids(authenticated_client) == ["anthropic/claude-new-key"]
    assert http.keys_seen == [_A_KEY, _B_KEY], "each listing dialled with its own key"


# ── every non-resolving outcome is seeds with zero egress ─────────────────────


def test_no_credential_serves_the_compiled_seeds_byte_identically_with_zero_egress(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    http = _LoudClient()
    _install(authenticated_client, http)

    plugin = anthropic_plugin_module.PLUGIN
    expected = [model_row(plugin, entry) for entry in plugin.register_models()]
    anthropic_rows = [r for r in _rows(authenticated_client) if r["owned_by"] == "anthropic"]

    assert anthropic_rows == expected, "byte-compatible static seeds"
    assert [r["id"] for r in anthropic_rows] == _seed_ids(settings)
    assert http.dialed == []


def test_an_unsupported_auth_type_serves_seeds_with_zero_egress(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An AUTHENTICATED oauth profile resolves — and is refused before any decrypt."""
    settings = _configure(monkeypatch)
    http = _LoudClient()
    _install(authenticated_client, http)
    _put_oauth_profile(authenticated_client)

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == []


def test_two_active_connections_are_ambiguous_and_serve_seeds_with_zero_egress(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: never an arbitrary pick — ambiguity funds no egress."""
    settings = _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _LoudClient()
    _install(authenticated_client, http)
    _create_connection(authenticated_client, "work", _A_KEY)
    _create_connection(authenticated_client, "personal", _B_KEY)

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == []


def test_a_profile_under_a_non_default_name_is_not_the_effective_credential(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hosted resolution is the ``default`` Profile — a named sibling does not join."""
    settings = _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CombinedClient()
    _install(authenticated_client, http)
    _store_key(authenticated_client, "work", _A_KEY)
    # Land the post-commit publication warm first: it dials for the "work" profile in
    # the background, and this test's claim is about what the LISTING funds after it.
    drain_private_catalog(authenticated_client)
    dials_after_publication = list(http.keys_seen)

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.keys_seen == dials_after_publication, "the listing funded no dial"


def test_the_discovery_kill_switch_still_serves_seeds_with_zero_egress(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    warm = _CombinedClient()
    _install(authenticated_client, warm)
    _store_key(authenticated_client, "default", _A_KEY)
    app = cast(FastAPI, authenticated_client.app)
    app.state.model_catalog = None
    app.state.profile_model_catalog = None
    http = _LoudClient()
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == []


# ── isolation: an account's rows are its own ──────────────────────────────────


def test_account_a_rows_never_appear_in_account_b_responses(
    authenticated_client: TestClient,
    provisioned_user_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CombinedClient()
    _install(authenticated_client, http)
    _store_key(authenticated_client, "default", _A_KEY)
    assert _anthropic_ids(authenticated_client) == ["anthropic/claude-a-only"]

    provisioned_user_factory("account-b")
    as_b = _login(authenticated_client, "account-b")

    b_ids = _anthropic_ids(authenticated_client, headers=as_b)
    assert "anthropic/claude-a-only" not in b_ids, "A's credential never lists for B"
    assert http.keys_seen == [_A_KEY], "B's request funded no dial with A's key"

    _store_key(authenticated_client, "default", _B_KEY, headers=as_b)
    assert _anthropic_ids(authenticated_client, headers=as_b) == ["anthropic/claude-b-only"]
    assert _anthropic_ids(authenticated_client) == ["anthropic/claude-a-only"], (
        "A's listing is unchanged by B's credential"
    )
    assert http.keys_seen == [_A_KEY, _B_KEY]


def test_openrouter_remains_one_global_listing_fetched_once_across_accounts(
    authenticated_client: TestClient,
    provisioned_user_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PUBLIC_GLOBAL is untouched: one deployment-wide fetch, identical for everyone."""
    _configure(monkeypatch)
    _enable_openrouter(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CombinedClient(openrouter_ids=["qwen/qwen3-coder"])
    _install(authenticated_client, http)
    _store_key(authenticated_client, "default", _A_KEY)

    a_rows = _rows(authenticated_client)
    provisioned_user_factory("account-b")
    b_rows = _rows(authenticated_client, headers=_login(authenticated_client, "account-b"))

    a_openrouter = [r["id"] for r in a_rows if r["owned_by"] == "openrouter"]
    b_openrouter = [r["id"] for r in b_rows if r["owned_by"] == "openrouter"]
    assert a_openrouter == b_openrouter == ["openrouter/qwen/qwen3-coder"]
    assert http.openrouter_dials == 1, "the public catalog is fetched once, not per account"
    assert http.keys_seen == [_A_KEY], "and no account credential funded it"


# ── the merged listing keeps its established shape ────────────────────────────


def test_live_private_rows_keep_the_registry_provider_order(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: row order follows the registry, not which upstream answered."""
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CombinedClient()
    _install(authenticated_client, http)

    def _provider_order(rows: list[dict]) -> list[str]:
        order: list[str] = []
        for row in rows:
            if row["owned_by"] not in order:
                order.append(row["owned_by"])
        return order

    seeded_order = _provider_order(_rows(authenticated_client))
    _store_key(authenticated_client, "default", _A_KEY)

    assert _provider_order(_rows(authenticated_client)) == seeded_order


def test_an_admitted_model_deduplicates_against_a_live_private_row(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    _install(authenticated_client, _CombinedClient())
    _store_key(authenticated_client, "default", _A_KEY)
    canonical = "anthropic/claude-a-only"
    app = cast(FastAPI, authenticated_client.app)
    app.state.admitted_models[canonical] = ModelEntry(
        model_name=canonical, litellm_params={"model": canonical}
    )

    ids = [r["id"] for r in _rows(authenticated_client)]
    assert ids.count(canonical) == 1
