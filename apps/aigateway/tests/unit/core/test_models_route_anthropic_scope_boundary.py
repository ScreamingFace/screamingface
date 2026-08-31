"""OME-1026 rework — the PUBLIC boundary: Anthropic is never live on ``GET /v1/models``.

FEATURE: two discovery scopes. OpenRouter's catalog needs no credential, so it stays a
public global listing. Anthropic's answers "what may THIS key call", so it became a
PRIVATE per-profile listing served only through
``GET /v1/auth/anthropic/profiles/{name}/models``.

STORY: as any account calling ``GET /v1/models`` I see Anthropic's compiled catalog —
never another account's entitlements, and never a listing derived from someone's key.

INVARIANT (the load-bearing one, asserted from several angles below): no credential-derived
Anthropic row can reach the shared ``/v1/models`` response, and the route causes ZERO
Anthropic catalog egress — even when an authenticated api-key profile exists, even with
``live_models`` on. Three independent mechanisms deny it: the plugin declares
``PROFILE_CREDENTIAL``, ``ModelCatalog`` refuses that scope before consulting the source,
and the plugin does not implement the public ``discover_live_models`` hook at all.

WHY this file replaced ``test_models_route_live_catalog_anthropic.py``: that file specified
the REJECTED architecture — one deployment-wide ``AIGW_ANTHROPIC_DISCOVERY_API_KEY`` whose
snapshot was published to every account. Its assertions are not weakened here; they are
INVERTED, because the behaviour they pinned is the behaviour the owner rejected.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.model_discovery_scope import DiscoveryScope
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.plugin_base import ModelEntry
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings

_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
# An id that exists ONLY upstream. If it ever appears in /v1/models, a credentialed
# listing leaked into the shared catalog.
_UPSTREAM_ONLY = "claude-opus-6-20270101"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _LoudCatalogClient:
    """Any Anthropic catalog dial is a failure.

    # WHY a raising client rather than a canned catalog: the assertion that matters is
    # that nothing is dialed at all. A client that answers would leave "not attempted"
    # indistinguishable from "attempted, then discarded" — both end in seeds.
    """

    def __init__(self) -> None:
        self.dialed: list[str] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
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
    app.state.model_catalog = ModelCatalog(clock=_Clock())


def _anthropic_ids(client: TestClient) -> list[str]:
    response = client.get("/v1/models")
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()["data"] if row["owned_by"] == "anthropic"]


def _seed_ids(settings: AnthropicPluginSettings) -> list[str]:
    return [f"anthropic/{entry.model_name}" for entry in settings.models]


async def _store_api_key_profile(client: TestClient, credential_blobs: Any) -> str:
    """An AUTHENTICATED api-key profile — the state that CAN do private discovery."""
    account_id = client.get("/v1/auth/me").json()["id"]
    await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )
    return account_id


# --------------------------------------------------------------------------------------
# The scope boundary at the shared catalog.
# --------------------------------------------------------------------------------------


def test_the_plugin_declares_a_private_scope_and_no_public_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _configure(monkeypatch)
    plugin = anthropic_plugin_module.PLUGIN

    assert settings.live_models is True, "discovery is ON for this whole file"
    assert plugin.model_discovery_scope() is DiscoveryScope.PROFILE_CREDENTIAL
    # INVARIANT (structural): the class does not DEFINE a public listing hook at all, so
    # the base default ("no source, no attempt, no connection") is what answers for it.
    # There is therefore no code that could produce credentialed rows for /v1/models.
    assert "discover_live_models" not in vars(type(plugin))
    assert "discover_profile_models" in vars(type(plugin)), "the private hook IS implemented"


@pytest.mark.asyncio
async def test_the_shared_catalog_refuses_the_private_scope_without_dialing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: refused BEFORE the source is consulted, so no cache slot is opened."""
    _configure(monkeypatch)
    http = _LoudCatalogClient()
    catalog = ModelCatalog(clock=_Clock())

    entries = await catalog.entries_for(
        cast(Any, anthropic_plugin_module.PLUGIN), client=http, limits=DiscoveryLimits()
    )

    assert entries is None, "the shared catalog has no Anthropic listing to serve"
    assert http.dialed == []
    assert (
        await catalog.ids_for(
            cast(Any, anthropic_plugin_module.PLUGIN), client=http, limits=DiscoveryLimits()
        )
        == frozenset()
    )


# --------------------------------------------------------------------------------------
# The public route: seeds only, always, with zero egress.
# --------------------------------------------------------------------------------------


def test_v1_models_lists_exactly_the_compiled_seeds_with_zero_egress(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    http = _LoudCatalogClient()
    _install(authenticated_client, http)

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == []
    assert f"anthropic/{_UPSTREAM_ONLY}" not in _anthropic_ids(authenticated_client)


@pytest.mark.asyncio
async def test_a_stored_api_key_profile_does_not_make_v1_models_live(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, credential_blobs: Any
) -> None:
    """The strongest form of the isolation claim.

    # WHY this case and not merely the credential-less one: a stored, AUTHENTICATED
    # api-key profile is exactly the state in which private discovery IS allowed. If the
    # shared route were going to borrow an account credential, it would happen here.
    """
    settings = _configure(monkeypatch)
    http = _LoudCatalogClient()
    _install(authenticated_client, http)
    await _store_api_key_profile(authenticated_client, credential_blobs)

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == [], "an account's credential never funds the shared listing"


def test_live_models_off_changes_nothing_at_the_public_boundary(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag governs the PRIVATE catalog; /v1/models looks identical either way."""
    settings = _configure(monkeypatch, live_models=False)
    http = _LoudCatalogClient()
    _install(authenticated_client, http)

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == []


def test_the_discovery_kill_switch_serves_seeds_with_zero_dials(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``AIGW_DISCOVERY_ENABLED=false`` silences Anthropic with everything else."""
    settings = _configure(monkeypatch)
    http = _LoudCatalogClient()
    _install(authenticated_client, http)
    app = cast(FastAPI, authenticated_client.app)
    app.state.model_catalog = None  # the shape build_model_catalog returns when disabled

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == []


def test_a_published_row_keeps_the_established_shape(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The row contract is unchanged by the rework: only WHERE live ids appear moved.
    settings = _configure(monkeypatch)
    _install(authenticated_client, _LoudCatalogClient())

    rows = authenticated_client.get("/v1/models").json()["data"]
    row = next(r for r in rows if r["id"] == _seed_ids(settings)[0])

    assert row["object"] == "model"
    assert row["owned_by"] == "anthropic"
    assert "supported_parameters" in row and "unsupported_parameter_behavior" in row


def test_operator_explicit_models_are_still_honoured(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    pinned = ModelEntry(
        model_name="claude-operator-pinned",
        litellm_params={"model": "anthropic/claude-operator-pinned"},
    )
    _configure(monkeypatch, models=[pinned])
    _install(authenticated_client, _LoudCatalogClient())

    assert _anthropic_ids(authenticated_client) == ["anthropic/claude-operator-pinned"]


# --------------------------------------------------------------------------------------
# Hygiene and coexistence.
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_credential_or_scope_material_appears_in_captured_logs(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    credential_blobs: Any,
    caplog: Any,
) -> None:
    _configure(monkeypatch)
    _install(authenticated_client, _LoudCatalogClient())
    await _store_api_key_profile(authenticated_client, credential_blobs)

    with caplog.at_level(logging.DEBUG):
        _anthropic_ids(authenticated_client)

    captured = "\n".join(record.getMessage() for record in caplog.records)
    assert "x-api-key" not in captured
    # A refused scope is a normal answer, not an operator-facing degradation event.
    assert "tier=" not in captured or "provider=anthropic tier=" not in captured


def test_anthropic_scope_refusal_leaves_other_providers_untouched(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    _install(authenticated_client, _LoudCatalogClient())

    rows = authenticated_client.get("/v1/models").json()["data"]

    assert [row["id"] for row in rows if row["owned_by"] == "openai"], (
        "other providers must still publish their own listings"
    )


def test_anthropic_rows_coexist_with_admitted_rows_deduplicated(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The merged listing keeps seeded and admitted rows distinct-but-once."""
    settings = _configure(monkeypatch)
    _install(authenticated_client, _LoudCatalogClient())
    canonical = _seed_ids(settings)[0]
    app = cast(FastAPI, authenticated_client.app)
    app.state.admitted_models[canonical] = ModelEntry(
        model_name=canonical, litellm_params={"model": canonical}
    )

    assert _anthropic_ids(authenticated_client).count(canonical) == 1


def test_dispatch_still_uses_the_callers_own_profile_credential(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Listing scope did not change dispatch: chat authenticates as the caller.

    # AIDEV-NOTE: catalog visibility is not dispatch readiness. Private discovery changed
    # what a profile OWNER can SEE; it added no model to the router and removed none.
    """
    settings = _configure(monkeypatch)
    _install(authenticated_client, _LoudCatalogClient())

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
    created = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "anthropic", "label": "chat", "api_key": "sk-ant-profile-key"},
    )
    assert created.status_code == 201, created.text

    canonical = _seed_ids(settings)[0]
    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            model_dump=lambda: {
                "id": "gen-live",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            }
        )

    with patch("litellm.acompletion", _fake_acompletion):
        response = authenticated_client.post(
            "/v1/chat/completions",
            json={"model": canonical, "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200, response.text
    assert captured["model"] == canonical
    assert "sk-ant-profile-key" in json.dumps(captured, default=str), (
        "the caller's own stored key funds the dispatch"
    )
