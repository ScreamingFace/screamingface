"""Successor-route coverage for behaviour only the retired Profile-route tests pinned.

# FEATURE: OME-1209 Stage E3 retired the 13 legacy Profile HTTP routes (they answer 410), and
# their tests went with them. Owner decision D4: each behaviour those tests alone pinned is pinned
# here again, on the Connection-era successor routes that now carry it — the native tenant surface
# `/v1/oauth/connections*`, the caller listing `/v1/provider-access`, and the D18 admin surface
# `/v1/admin/accounts/{account_id}/connections*`.
# INVARIANT: an admin-written key belongs to exactly one tenant — that tenant sees it, no other
# tenant does, and the D18 DELETE leaves no stored credential behind.
# INVARIANT: a `defaults` member on a NATIVE tenant writer is ignored, not refused — only the
# D18 admin PUT refuses it (`defaults_not_accepted`). This pins today's behaviour; a change to it
# is a deliberate contract decision, not a refactor.
"""

from __future__ import annotations

import json
import sqlite3
from ipaddress import ip_network
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)

ADMIN = "admin@openmined.org"
TENANT = "tenant@openmined.org"
OTHER_TENANT = "other-tenant@openmined.org"
POD_NETWORK = ip_network("10.0.0.0/8")
ANTHROPIC_KEY = "sk-ant-api03-successor-coverage-0001"
GEMINI_KEY = "AIzaSy-successor-coverage-gemini-0001"
# WHY `gemini-cli`: the Gemini plugin registers under that provider id; a bare `gemini` is unknown.
GEMINI = "gemini-cli"
DEFAULTS = {"temperature": 0.1, "system_prompt": "be terse"}


class _ValidKeys:
    """A validation service that accepts every key — key validation is not the subject here."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def validate(self, _plugin: Any, provider: str, api_key: str) -> ApiKeyValidationResult:
        self.calls.append((provider, api_key))
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


@pytest.fixture
def valid_keys() -> _ValidKeys:
    return _ValidKeys()


@pytest.fixture
def tenant_client(authenticated_client: TestClient, valid_keys: _ValidKeys) -> TestClient:
    _app(authenticated_client).state.api_key_validation_service = valid_keys
    return authenticated_client


@pytest.fixture
def admin_client(client: TestClient, valid_api_key_readiness: None) -> TestClient:
    del valid_api_key_readiness
    settings = _app(client).state.settings
    settings.auth_mode = "cloudflare_headers"
    settings.allowed_networks = (POD_NETWORK,)
    settings.admin_emails = frozenset({ADMIN})
    return TestClient(client.app, client=("10.1.2.3", 50000))


def _as(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


def _tenant(admin_client: TestClient, email: str) -> str:
    resp = admin_client.post("/v1/admin/accounts", json={"email": email}, headers=_as(ADMIN))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _admin_put_key(admin_client: TestClient, account_id: str, provider: str = "anthropic") -> None:
    resp = admin_client.put(
        f"/v1/admin/accounts/{account_id}/connections/{provider}/api-key",
        json={"api_key": ANTHROPIC_KEY},
        headers=_as(ADMIN),
    )
    assert resp.status_code == 200, resp.text


def _blob_services_holding(db_path: Any, account_id: str) -> list[str]:
    """Every `credential_blobs` service whose name carries `account_id`."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("select service from credential_blobs").fetchall()
    return [service for (service,) in rows if account_id in service]


def _create_api_key_connection(client: TestClient, label: str = "work") -> dict[str, Any]:
    resp = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "anthropic", "label": label, "api_key": ANTHROPIC_KEY},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_native_oauth_start_refuses_an_unknown_provider_with_404(tenant_client) -> None:
    resp = tenant_client.post("/v1/oauth/connections", json={"provider": "no-such-provider"})

    assert resp.status_code == 404
    assert resp.json() == {"detail": {"code": "unknown_provider", "provider": "no-such-provider"}}
    assert tenant_client.get("/v1/oauth/connections").json()["connections"] == []


def test_native_oauth_start_refuses_a_provider_without_oauth_with_400(tenant_client) -> None:
    resp = tenant_client.post("/v1/oauth/connections", json={"provider": "ollama"})

    assert resp.status_code == 400
    assert resp.json() == {"detail": {"code": "provider_does_not_use_oauth"}}
    assert tenant_client.get("/v1/oauth/connections").json()["connections"] == []


def test_an_admin_written_key_is_visible_to_its_tenant_only(client, admin_client) -> None:
    tenant = _tenant(admin_client, TENANT)
    _tenant(admin_client, OTHER_TENANT)

    _admin_put_key(admin_client, tenant)

    owner_rows = admin_client.get("/v1/oauth/connections", headers=_as(TENANT)).json()
    assert [(c["provider"], c["auth_type"], c["status"]) for c in owner_rows["connections"]] == [
        ("anthropic", "api_key", "active")
    ]
    assert ANTHROPIC_KEY not in json.dumps(owner_rows)
    owner_access = admin_client.get("/v1/provider-access", headers=_as(TENANT)).json()
    assert {"provider": "anthropic", "status": "connected"} in owner_access["providers"]

    other_rows = admin_client.get("/v1/oauth/connections", headers=_as(OTHER_TENANT)).json()
    assert other_rows["connections"] == []
    other_access = admin_client.get("/v1/provider-access", headers=_as(OTHER_TENANT)).json()
    assert {"provider": "anthropic", "status": "not_connected"} in other_access["providers"]


def test_an_admin_delete_removes_the_tenants_stored_credential(
    client, admin_client, credential_blobs
) -> None:
    tenant = _tenant(admin_client, TENANT)
    _admin_put_key(admin_client, tenant)
    assert _blob_services_holding(credential_blobs.db_path, tenant), "the PUT stored a blob"

    resp = admin_client.delete(
        f"/v1/admin/accounts/{tenant}/connections/anthropic", headers=_as(ADMIN)
    )

    assert resp.status_code == 204
    assert _blob_services_holding(credential_blobs.db_path, tenant) == []
    rows = admin_client.get("/v1/oauth/connections", headers=_as(TENANT)).json()["connections"]
    assert [row for row in rows if row["status"] == "active"] == []


def test_a_native_gemini_api_key_is_stored_and_listed_for_the_caller(
    tenant_client, valid_keys, credential_blobs
) -> None:
    resp = tenant_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": GEMINI, "label": "gemini-key", "api_key": GEMINI_KEY},
    )

    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert (created["provider"], created["auth_type"], created["status"]) == (
        GEMINI,
        "api_key",
        "active",
    )
    assert GEMINI_KEY not in resp.text
    assert valid_keys.calls == [(GEMINI, GEMINI_KEY)]
    listed = tenant_client.get("/v1/oauth/connections").json()["connections"]
    assert [row["id"] for row in listed] == [created["id"]]
    service = created["credential_locator"]["service"]
    stored = credential_blobs.read(service, "default")
    assert stored is not None and json.loads(stored)["api_key"] == GEMINI_KEY
    assert GEMINI_KEY not in (credential_blobs.read_raw(service, "default") or "")


# WHY ignored, not refused: the native request models declare no `defaults` and keep Pydantic's
# default `extra="ignore"`; only the D18 admin PUT reads the raw body and refuses the member.


@pytest.mark.parametrize("defaults", [None, DEFAULTS], ids=["null", "object"])
def test_native_api_key_create_ignores_a_defaults_member(tenant_client, defaults) -> None:
    resp = tenant_client.post(
        "/v1/oauth/connections/api-key",
        json={
            "provider": "anthropic",
            "label": "work",
            "api_key": ANTHROPIC_KEY,
            "defaults": defaults,
        },
    )

    assert resp.status_code == 201, resp.text
    assert "defaults" not in resp.json()
    assert "be terse" not in resp.text


@pytest.mark.parametrize("defaults", [None, DEFAULTS], ids=["null", "object"])
def test_native_api_key_replace_ignores_a_defaults_member(tenant_client, defaults) -> None:
    connection = _create_api_key_connection(tenant_client)

    resp = tenant_client.put(
        f"/v1/oauth/connections/{connection['id']}/api-key",
        json={"api_key": ANTHROPIC_KEY + "-2", "defaults": defaults},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == connection["id"]
    assert "defaults" not in resp.json()


@pytest.mark.parametrize("defaults", [None, DEFAULTS], ids=["null", "object"])
def test_native_patch_ignores_a_defaults_member(tenant_client, defaults) -> None:
    connection = _create_api_key_connection(tenant_client)

    resp = tenant_client.patch(
        f"/v1/oauth/connections/{connection['id']}",
        json={"label": "renamed", "defaults": defaults},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["label"] == "renamed"
    assert "defaults" not in resp.json()


@pytest.mark.parametrize("defaults", [None, DEFAULTS], ids=["null", "object"])
def test_native_oauth_start_ignores_a_defaults_member(tenant_client, defaults) -> None:
    resp = tenant_client.post(
        "/v1/oauth/connections",
        json={"provider": "anthropic", "label": "oauth-work", "defaults": defaults},
    )

    assert resp.status_code == 201, resp.text
    assert set(resp.json()) == {"connection_id", "authorize_url", "state", "expires_in"}
    assert "be terse" not in resp.text
