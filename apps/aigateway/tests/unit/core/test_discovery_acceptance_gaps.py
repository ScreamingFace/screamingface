"""OME-1026 remediation F8 — the acceptance claims the earlier suite did not actually make.

Three gaps the independent review identified, each closed by a test that fails for the
right reason if the behavior regresses:

1. **A credential that already existed.** The earlier "upgrade" test stored the key
   through the current PUT route moments before the listing request, so it proved the
   write path, not the read path. The real claim is that a key persisted by an EARLIER
   process is usable by a NEW one — this file restarts the app to prove it.
2. **OpenRouter's global snapshot really is shared.** That was asserted only through a
   scope declaration. Here two different accounts read ``GET /v1/models`` and the
   upstream is dialed once.
3. **A discovered-only private model is dispatchable.** Listing is not dispatch
   readiness, and which of the two applies to a private discovered id was unpinned.
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

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
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.live_models import LIVE_MODELS_URL
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings
from tests.conftest import drain_private_catalog

_ANTHROPIC_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_LIST_URL = "/v1/auth/anthropic/profiles/{name}/models"
_DISCOVERED = "claude-restart-only-4-9"
_KEY = "sk-ant-persisted-before-startup"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _AnthropicCatalogClient:
    def __init__(self, ids: list[str]) -> None:
        self._ids = list(ids)
        self.keys_seen: list[str] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert headers is not None
        self.keys_seen.append(headers["x-api-key"])
        if url != _ANTHROPIC_FIRST_PAGE:
            raise AssertionError(f"unexpected dial: {url}")
        body = json.dumps(
            {"data": [{"id": i, "type": "model"} for i in self._ids], "has_more": False}
        )
        return RawResponse(status=200, content_type="application/json", body=body)


class _OpenRouterCatalogClient:
    def __init__(self, ids: list[str]) -> None:
        self._body = json.dumps(
            {"data": [{"id": i} for i in ids], "links": {"next": None}, "total_count": len(ids)}
        )
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        return RawResponse(status=200, content_type="application/json", body=self._body)


def _accept_any_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


def _install_anthropic(client: TestClient, http: Any) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


# ── 1. a credential that already existed before this process started ───────────


def test_a_credential_persisted_by_an_earlier_process_drives_discovery(
    credential_blobs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A RESTART, not a write followed by a read.

    The first app stores the key and is then shut down — its private catalog, its
    snapshot and its in-flight tasks all go with it. A second app is built against the
    same database and asked for the listing. Nothing re-enters the credential, so the
    only way the discovered row can appear is the persisted ``credential_blobs`` row
    plus the persisted profile index.

    # WHY the earlier test did not establish this: it PUT the key through the current
    # route moments before reading, inside one process. That exercises the write path
    # and a warm in-memory catalog — it cannot distinguish "usable after a restart"
    # from "usable because we just wrote it".
    """
    from aigateway.main import create_app

    database_url = f"sqlite://{credential_blobs.db_path}"
    monkeypatch.setenv("AIGATEWAY_DATABASE_URL", database_url)
    monkeypatch.setenv("AIGATEWAY_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("AIGATEWAY_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AIGATEWAY_PROVISIONING_TOKEN", "p" * 32)
    from tests.conftest import TEST_SECRET_KEY

    monkeypatch.setenv("AIGATEWAY_SECRET_KEY", base64.b64encode(TEST_SECRET_KEY).decode())
    monkeypatch.setenv("AIGW_ALLOWED_NETWORKS", "10.0.0.0/8")
    _accept_any_api_key(monkeypatch)
    monkeypatch.setattr(
        anthropic_plugin_module.PLUGIN, "settings", AnthropicPluginSettings(live_models=True)
    )

    # ── process 1: publish the credential, then go away ──
    with TestClient(create_app(), client=("10.1.2.3", 50000)) as first:
        first.headers.update(
            {"Authorization": f"Bearer {_login(first, 'admin', 'test-admin-password')}"}
        )
        _install_anthropic(first, _AnthropicCatalogClient([_DISCOVERED]))
        stored = first.put("/v1/auth/anthropic/profiles/persisted/api-key", json={"api_key": _KEY})
        assert stored.status_code == 200, stored.text
        app_one = cast(FastAPI, first.app)
        drain_private_catalog(first)

    # ── process 2: a brand-new app, catalog and snapshot store over the same rows ──
    http = _AnthropicCatalogClient([_DISCOVERED])
    with TestClient(create_app(), client=("10.1.2.3", 50000)) as second:
        assert cast(FastAPI, second.app) is not app_one, "the restart must be a NEW app"
        second.headers.update(
            {"Authorization": f"Bearer {_login(second, 'admin', 'test-admin-password')}"}
        )
        _install_anthropic(second, http)

        listing = second.get(_LIST_URL.format(name="persisted"))

        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["status"] == "fresh", body
        assert [row["id"] for row in body["data"]] == [f"anthropic/{_DISCOVERED}"], body
        # INVARIANT: the dial used the PERSISTED key, decrypted by the new process.
        assert http.keys_seen == [_KEY], http.keys_seen

    # AIDEV-NOTE: no explicit connection teardown here on purpose — the
    # ``credential_blobs`` fixture owns the database lifecycle, and the second
    # TestClient's own shutdown already closed the pool.


# ── 2. the PUBLIC snapshot really is shared across accounts ───────────────────


def test_two_accounts_share_one_openrouter_snapshot_end_to_end(
    client: TestClient, provisioned_user_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The PUBLIC_GLOBAL contract, measured rather than declared.

    A scope declaration test proves the provider says "public". This proves the
    consequence: two different authenticated accounts read the same rows out of ONE
    upstream fetch, which is exactly what makes a shared cache correct here — the
    listing is derived from no credential at all.
    """
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )
    http = _OpenRouterCatalogClient(["openai/gpt-5", "qwen/qwen3-coder"])
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    app.state.model_catalog = ModelCatalog(clock=_Clock())
    provisioned_user_factory("shared-snapshot-user")

    def _openrouter_ids(token: str) -> list[str]:
        response = client.get("/v1/models", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        return [row["id"] for row in response.json()["data"] if row["owned_by"] == "openrouter"]

    admin_rows = _openrouter_ids(_login(client, "admin", "test-admin-password"))
    user_rows = _openrouter_ids(_login(client, "shared-snapshot-user", "test-user-password"))

    assert admin_rows == ["openrouter/openai/gpt-5", "openrouter/qwen/qwen3-coder"]
    # INVARIANT (PUBLIC_GLOBAL): byte-identical rows for both accounts...
    assert user_rows == admin_rows
    # ...out of ONE upstream fetch. A per-account catalog would have dialed twice.
    assert http.dialed == [LIVE_MODELS_URL], http.dialed


# ── 3. a discovered-only PRIVATE id is dispatchable under its own profile ──────


def test_a_discovered_only_private_id_is_dispatchable_under_its_own_profile(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins which of "listing" and "dispatch readiness" a private discovered id gets.

    The private listing's own AIDEV-NOTE says listing is not dispatch readiness, and the
    review found that verdict unpinned. It is: dispatch resolves the provider from the
    canonical prefix and funds the call with the caller's own profile credential, so a
    discovered-only id DISPATCHES — the private snapshot neither authorizes it nor is
    consulted. This test states that, and pins the credential that funds it.

    # WHY the transport is stubbed rather than exercised: an unstubbed dispatch really
    # does leave the process. The suite's no-egress tripwire guards the DISCOVERY client
    # only, so a chat test without this patch reaches the live provider — confirmed
    # once, accidentally, while writing this file.
    """
    monkeypatch.setattr(
        anthropic_plugin_module.PLUGIN, "settings", AnthropicPluginSettings(live_models=True)
    )
    _accept_any_api_key(monkeypatch)
    _install_anthropic(authenticated_client, _AnthropicCatalogClient([_DISCOVERED]))
    stored = authenticated_client.put(
        "/v1/auth/anthropic/profiles/work/api-key", json={"api_key": _KEY}
    )
    assert stored.status_code == 200, stored.text
    canonical = f"anthropic/{_DISCOVERED}"
    listing = authenticated_client.get(_LIST_URL.format(name="work"))
    assert canonical in {row["id"] for row in listing.json()["data"]}, listing.text

    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            model_dump=lambda: {
                "id": "gen-private-discovered",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            }
        )

    with patch("litellm.acompletion", _fake_acompletion):
        chat = authenticated_client.post(
            "/v1/chat/completions",
            headers={"X-Profile": "work"},
            json={"model": canonical, "messages": [{"role": "user", "content": "hi"}]},
        )

    assert chat.status_code == 200, chat.text
    assert captured["model"] == canonical
    # INVARIANT: the caller's OWN stored profile key funds it — the same credential the
    # private listing was discovered with, and never a deployment key.
    assert _KEY in json.dumps(captured, default=str), "the profile's own key funds dispatch"


def test_dispatch_does_not_depend_on_the_private_snapshot(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: the snapshot is not an authorization input.

    With the private catalog switched off entirely — no snapshot, no discovery egress —
    the very same id still dispatches. So the listing describes what a credential can
    see; it never decides what the gateway will route.
    """
    monkeypatch.setattr(
        anthropic_plugin_module.PLUGIN, "settings", AnthropicPluginSettings(live_models=True)
    )
    _accept_any_api_key(monkeypatch)
    _install_anthropic(authenticated_client, _AnthropicCatalogClient([_DISCOVERED]))
    stored = authenticated_client.put(
        "/v1/auth/anthropic/profiles/work/api-key", json={"api_key": _KEY}
    )
    assert stored.status_code == 200, stored.text
    drain_private_catalog(authenticated_client)
    app = cast(FastAPI, authenticated_client.app)
    app.state.profile_model_catalog = None  # the discovery kill switch's shape

    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            model_dump=lambda: {
                "id": "gen-no-snapshot",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            }
        )

    with patch("litellm.acompletion", _fake_acompletion):
        chat = authenticated_client.post(
            "/v1/chat/completions",
            headers={"X-Profile": "work"},
            json={
                "model": f"anthropic/{_DISCOVERED}",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert chat.status_code == 200, chat.text
    assert captured["model"] == f"anthropic/{_DISCOVERED}"
