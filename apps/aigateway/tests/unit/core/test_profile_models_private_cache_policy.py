"""OME-1026 remediation F1 — the private listing must be uncacheable by intermediaries.

FEATURE: the private model list. Its body is one account's entitlements, so the
HTTP response itself — not just the in-process store — has to be unshareable.

STORY: as an account owner behind a CDN or mesh proxy, my private model list is
never handed to another account that requested the same URL.

INVARIANT (why this file exists at all): in ``cloudflare_headers`` mode the caller
identity is ``X-User-Email``, NOT ``Authorization``. Two accounts therefore issue
byte-identical request lines for ``/v1/auth/anthropic/profiles/work/models`` and
differ only in an identity header. A shared cache keyed on the URL alone would
serve account A's catalog to account B. ``Cache-Control: private, no-store`` plus a
``Vary`` that names every mode's identity input is what forbids that.
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
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings

_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_URL = "/v1/auth/anthropic/profiles/{name}/models"
_A_KEY = "sk-ant-cache-policy-a"
_B_KEY = "sk-ant-cache-policy-b"
_EMAIL_A = "cache-a@openmined.org"
_EMAIL_B = "cache-b@openmined.org"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _CatalogClient:
    """Answers per calling key, exactly as the real credentialed catalog does."""

    def __init__(self) -> None:
        self._per_key = {_A_KEY: ["claude-a-private"], _B_KEY: ["claude-b-private"]}
        self.keys_seen: list[str] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert headers is not None
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


def _assert_private(response: Any) -> None:
    """The one policy every response from this endpoint must carry.

    # WHY ``no-store`` and not merely ``private``: ``private`` still permits the
    # caller's own browser cache to retain a credential-derived catalog on disk, and
    # a misconfigured intermediary that ignores ``private`` has nothing else to stop
    # it. ``no-store`` is the directive that forbids writing the body down anywhere.
    """
    cache_control = response.headers.get("cache-control", "")
    assert "no-store" in cache_control, response.headers
    assert "private" in cache_control, response.headers
    vary = response.headers.get("vary", "")
    # INVARIANT: every supported auth mode's identity input is named. Bearer mode
    # identifies the caller by Authorization; cloudflare_headers mode by X-User-Email.
    # Omitting either leaves that mode's responses interchangeable to a shared cache.
    assert "Authorization" in vary, response.headers
    assert "X-User-Email" in vary, response.headers


# ── the policy holds on every exit, not only the happy path ───────────────────


def test_a_successful_private_listing_is_marked_unshareable(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    stored = authenticated_client.put(
        "/v1/auth/anthropic/profiles/work/api-key", json={"api_key": _A_KEY}
    )
    assert stored.status_code == 200, stored.text

    response = authenticated_client.get(_URL.format(name="work"))

    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["data"]] == ["anthropic/claude-a-private"]
    _assert_private(response)


def test_an_unknown_provider_error_is_marked_unshareable(
    authenticated_client: TestClient,
) -> None:
    """# WHY errors too: a raised ``HTTPException`` is rendered from the EXCEPTION's
    own headers, so a policy set only on the injected response is invisible to it.
    """
    response = authenticated_client.get("/v1/auth/nope/profiles/work/models")

    assert response.status_code == 404
    _assert_private(response)


def test_a_missing_profile_error_is_marked_unshareable(authenticated_client: TestClient) -> None:
    response = authenticated_client.get(_URL.format(name="never-created"))

    assert response.status_code == 404
    _assert_private(response)


def test_the_kill_switch_fallback_is_marked_unshareable(
    authenticated_client: TestClient, credential_blobs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even the seeds-only answer names the profile, so it stays per-account."""
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    stored = authenticated_client.put(
        "/v1/auth/anthropic/profiles/work/api-key", json={"api_key": _A_KEY}
    )
    assert stored.status_code == 200, stored.text
    app = cast(FastAPI, authenticated_client.app)
    app.state.profile_model_catalog = None

    response = authenticated_client.get(_URL.format(name="work"))

    assert response.status_code == 200
    assert response.json()["reason"] == "discovery_disabled"
    _assert_private(response)


# ── the cloudflare_headers mode this policy exists for ────────────────────────


def test_two_header_mode_accounts_get_different_bodies_from_one_url(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact schedule a shared cache would break.

    Both callers request the SAME url and differ only in ``X-User-Email``. Each must
    receive its own catalog, and each response must forbid any shared cache from
    reusing it for the other.
    """
    app = cast(FastAPI, client.app)
    app.state.settings.auth_mode = "cloudflare_headers"
    _configure(monkeypatch)
    _accept_any_api_key(monkeypatch)
    http = _CatalogClient()
    _install(client, http)

    for email, key in ((_EMAIL_A, _A_KEY), (_EMAIL_B, _B_KEY)):
        stored = client.put(
            "/v1/auth/anthropic/profiles/work/api-key",
            json={"api_key": key},
            headers={"X-User-Email": email},
        )
        assert stored.status_code == 200, stored.text

    a = client.get(_URL.format(name="work"), headers={"X-User-Email": _EMAIL_A})
    b = client.get(_URL.format(name="work"), headers={"X-User-Email": _EMAIL_B})

    assert a.request.url == b.request.url, "the leak this guards needs one shared url"
    assert [row["id"] for row in a.json()["data"]] == ["anthropic/claude-a-private"]
    assert [row["id"] for row in b.json()["data"]] == ["anthropic/claude-b-private"]
    _assert_private(a)
    _assert_private(b)
