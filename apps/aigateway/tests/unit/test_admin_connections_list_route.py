"""`GET /v1/admin/accounts/{account_id}/connections` — the D18 successor LIST (OME-1497, G1 part 1).

# FEATURE: OME-1138 D18 (contract §2-§4, §6.1, §7) — an admin reads one tenant's provider
# credentials as neutral Connections: no Profile name, id, selector, defaults or key on the wire.
# STORY: as an operator in the Admin console, I see each provider once, with its auth type and
# state, or a conflict telling me why it cannot be managed — and nothing about the account is
# cached by a browser or proxy on the way.
# INVARIANT: every response of the new route — success, auth refusal, 4xx and 503 — carries
# `Cache-Control: private, no-store`; the legacy admin routes are untouched.
"""

from __future__ import annotations

import logging
from ipaddress import ip_network
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tortoise.exceptions import OperationalError

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.provider_access.models import ProviderCredentialSlot
from aigateway.core.secrets.mixin import SecretDecryptionError
from aigateway.routes import admin_connections

ADMIN = "admin@openmined.org"
POD_NETWORK = ip_network("10.0.0.0/8")
NO_STORE = "private, no-store"
DTO_FIELDS = {"provider", "auth_type", "credential_state", "masked_key_hint", "last_refreshed_at"}


def _admin(client) -> TestClient:
    client.app.state.settings.auth_mode = "cloudflare_headers"
    client.app.state.settings.allowed_networks = (POD_NETWORK,)
    client.app.state.settings.admin_emails = frozenset({ADMIN})
    return TestClient(client.app, client=("10.1.2.3", 50000))


def _headers(**extra: str) -> dict[str, str]:
    return {"X-User-Email": ADMIN, **extra}


def _create_account(admin_client: TestClient, email: str) -> str:
    resp = admin_client.post("/v1/admin/accounts", json={"email": email}, headers=_headers())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _call(client: TestClient, fn: Any, *args: Any, **kwargs: Any) -> Any:
    async def run() -> Any:
        return await fn(*args, **kwargs)

    # WHY the base client: it is the one whose lifespan initialized the database.
    portal = client.portal
    assert portal is not None, "the base client fixture is entered"
    return portal.call(run)


def _api_key_connection(client: TestClient, account_id: str, provider: str) -> str:
    connection_id = uuid4()
    _call(
        client,
        OAuthConnectionStore().create_api_key,
        account_id=account_id,
        provider=provider,
        label=f"api-key-{connection_id}",
        connection_id=connection_id,
    )
    return str(connection_id)


def _list(admin_client: TestClient, account_id: str, **headers: str):
    return admin_client.get(
        f"/v1/admin/accounts/{account_id}/connections", headers=_headers(**headers)
    )


@pytest.fixture
def admin_client(client) -> TestClient:
    return _admin(client)


# --- the happy path -----------------------------------------------------------------------------


def test_an_admin_lists_a_tenants_connections_as_neutral_rows(client, admin_client) -> None:
    tenant = _create_account(admin_client, "tenant@openmined.org")
    connection_id = _api_key_connection(client, tenant, "anthropic")

    resp = _list(admin_client, tenant)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "connections": [
            {
                "provider": "anthropic",
                "auth_type": "api_key",
                "credential_state": "active",
                "masked_key_hint": None,
                "last_refreshed_at": None,
            }
        ],
        "conflicts": [],
    }
    assert set(body["connections"][0]) == DTO_FIELDS
    # No public Connection id, label or selector anywhere on the wire.
    assert connection_id not in resp.text
    assert "api-key-" not in resp.text
    assert resp.headers["cache-control"] == NO_STORE


def test_the_listing_is_scoped_to_the_target_account(client, admin_client) -> None:
    tenant = _create_account(admin_client, "one@openmined.org")
    other = _create_account(admin_client, "two@openmined.org")
    _api_key_connection(client, other, "anthropic")

    resp = _list(admin_client, tenant)

    assert resp.json() == {"connections": [], "conflicts": []}


def test_a_conflict_is_a_provider_scoped_detail(client, admin_client) -> None:
    tenant = _create_account(admin_client, "conflicted@openmined.org")
    _api_key_connection(client, tenant, "anthropic")
    _api_key_connection(client, tenant, "anthropic")

    resp = _list(admin_client, tenant)

    assert resp.status_code == 200
    assert resp.json() == {
        "connections": [],
        "conflicts": [
            {
                "provider": "anthropic",
                "code": "credential_pair_ambiguous",
                "message": "The provider credential cannot be addressed unambiguously.",
            }
        ],
    }


def test_the_listing_changes_no_marker(client, admin_client) -> None:
    tenant = _create_account(admin_client, "readonly@openmined.org")
    _api_key_connection(client, tenant, "anthropic")

    async def markers() -> list[dict[str, Any]]:
        return await ProviderCredentialSlot.filter(account_id=tenant).values()

    before = _call(client, markers)
    assert _list(admin_client, tenant).status_code == 200
    assert _call(client, markers) == before


# --- refusals -----------------------------------------------------------------------------------


def test_an_unknown_account_is_404_and_not_cached(client, admin_client) -> None:
    resp = _list(admin_client, str(uuid4()))

    assert resp.status_code == 404
    assert resp.json() == {"detail": {"code": "account_not_found"}}
    assert resp.headers["cache-control"] == NO_STORE


def test_a_malformed_account_id_is_422_and_not_cached(client, admin_client) -> None:
    resp = _list(admin_client, "not-a-uuid")

    assert resp.status_code == 422
    assert resp.headers["cache-control"] == NO_STORE


def test_a_caller_who_is_not_an_admin_is_refused_and_not_cached(client, admin_client) -> None:
    tenant = _create_account(admin_client, "guarded@openmined.org")

    resp = admin_client.get(
        f"/v1/admin/accounts/{tenant}/connections", headers={"X-User-Email": "x@openmined.org"}
    )

    assert resp.status_code == 403
    assert resp.headers["cache-control"] == NO_STORE


def test_an_unidentified_caller_is_refused_and_not_cached(client, admin_client) -> None:
    tenant = _create_account(admin_client, "anon@openmined.org")

    resp = admin_client.get(f"/v1/admin/accounts/{tenant}/connections")

    assert resp.status_code == 401
    assert resp.headers["cache-control"] == NO_STORE


@pytest.mark.parametrize("value", ["default", "work"])
def test_a_nonblank_x_profile_is_refused_without_echo(client, admin_client, value) -> None:
    tenant = _create_account(admin_client, f"selector-{value}@openmined.org")

    resp = _list(admin_client, tenant, **{"X-Profile": value})

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "x_profile_unsupported"
    assert value not in resp.text
    assert resp.headers["cache-control"] == NO_STORE


def test_a_repeated_x_profile_with_a_blank_first_value_is_still_refused(
    client, admin_client
) -> None:
    tenant = _create_account(admin_client, "repeated@openmined.org")

    resp = admin_client.get(
        f"/v1/admin/accounts/{tenant}/connections",
        headers=[("X-User-Email", ADMIN), ("X-Profile", " "), ("X-Profile", "work")],
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "x_profile_unsupported"


def test_a_blank_x_profile_counts_as_absent(client, admin_client) -> None:
    tenant = _create_account(admin_client, "blank@openmined.org")

    resp = _list(admin_client, tenant, **{"X-Profile": "  "})

    assert resp.status_code == 200


def test_a_store_outage_refuses_the_whole_list(client, admin_client, monkeypatch) -> None:
    tenant = _create_account(admin_client, "outage@openmined.org")
    _api_key_connection(client, tenant, "anthropic")

    async def undecodable(*_args: Any, **_kwargs: Any) -> Any:
        raise SecretDecryptionError("failed to decrypt credential blob service='x'")

    monkeypatch.setattr(OAuthConnectionStore, "list", undecodable)

    resp = _list(admin_client, tenant)

    assert resp.status_code == 503
    assert resp.json() == {
        "detail": {
            "code": "credential_store_read_unavailable",
            "message": "Credential store is temporarily unavailable. Try again.",
        }
    }
    assert "decrypt" not in resp.text
    assert resp.headers["cache-control"] == NO_STORE


def test_an_inconsistent_pair_refuses_the_whole_list_naming_the_provider(
    client, admin_client
) -> None:
    tenant = _create_account(admin_client, "inconsistent@openmined.org")
    connection_id = _api_key_connection(client, tenant, "anthropic")

    async def corrupt() -> None:
        await OAuthConnection.filter(id=connection_id).update(status="unavailable")

    _call(client, corrupt)

    resp = _list(admin_client, tenant)

    assert resp.status_code == 503
    assert resp.json() == {
        "detail": {
            "code": "credential_authority_unavailable",
            "message": "Credential state is temporarily unavailable. Retry later.",
            "provider": "anthropic",
        }
    }
    assert resp.headers["cache-control"] == NO_STORE


# --- audit and contract -------------------------------------------------------------------------


def test_the_audit_line_names_the_actor_and_the_final_status(client, admin_client, caplog) -> None:
    tenant = _create_account(admin_client, "audited@openmined.org")
    caplog.set_level(logging.INFO, logger="aigateway.routes.admin")

    _list(admin_client, tenant, **{"X-Profile": "work"})

    lines = [r.getMessage() for r in caplog.records if "admin_action" in r.getMessage()]
    assert any(
        f"actor={ADMIN}" in line and "status_code=400" in line and "/connections" in line
        for line in lines
    ), lines


def test_the_openapi_contract_names_the_successor_and_drops_the_legacy_operations(
    client,
    admin_client,
) -> None:
    schema = admin_client.get("/openapi.json").json()

    operation = schema["paths"]["/v1/admin/accounts/{account_id}/connections"]["get"]
    assert operation["operationId"] == "list_admin_account_connections"
    assert operation["tags"] == ["Admin"]
    assert operation["security"] == [{"CloudflareUserEmail": []}]
    components = schema["components"]["schemas"]
    for name in ("AdminConnectionOut", "AdminConnectionConflictOut", "AdminConnectionList"):
        assert name in components
    assert set(components["AdminConnectionOut"]["properties"]) == DTO_FIELDS
    assert set(components["AdminConnectionOut"]["required"]) == DTO_FIELDS
    # The legacy surface is retired (OME-1209 Stage E3): no admin Profile path, no Profile schema.
    assert "/v1/admin/accounts/{account_id}/profiles" not in schema["paths"]
    assert "AdminProfileOut" not in components


def test_a_store_outage_at_the_account_lookup_is_a_503_and_not_cached(
    client, admin_client, monkeypatch
) -> None:
    # The account lookup is the request's first database read: an outage there is the same
    # whole-request store refusal as one in the inventory, never a bare 500.
    tenant = _create_account(admin_client, "lookup-outage@openmined.org")

    async def down(*_args: Any, **_kwargs: Any) -> Any:
        raise OperationalError("server closed the connection unexpectedly")

    monkeypatch.setattr(admin_connections, "_require_account", down)

    resp = _list(admin_client, tenant)

    assert resp.status_code == 503
    assert resp.json() == {
        "detail": {
            "code": "credential_store_read_unavailable",
            "message": "Credential store is temporarily unavailable. Try again.",
        }
    }
    assert "server closed" not in resp.text
    assert resp.headers["cache-control"] == NO_STORE


def test_an_unexpected_500_is_sanitized_and_not_cached(client, admin_client, monkeypatch) -> None:
    tenant = _create_account(admin_client, "unexpected@openmined.org")

    async def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("must-not-cross")

    monkeypatch.setattr(admin_connections, "_require_account", broken)
    no_raise = TestClient(
        admin_client.app,
        client=("10.1.2.3", 50000),
        raise_server_exceptions=False,
    )

    resp = _list(no_raise, tenant)

    assert resp.status_code == 500
    assert resp.json()["detail"]["code"] == "gateway_internal_error"
    assert "must-not-cross" not in resp.text
    assert resp.headers["cache-control"] == NO_STORE


@pytest.mark.parametrize("method", ["POST", "OPTIONS", "CONNECT", "TRACE"])
def test_an_authenticated_unsupported_method_is_audited_and_not_cached(
    admin_client, caplog, method
) -> None:
    account_id = str(uuid4())
    caplog.set_level(logging.INFO, logger="aigateway.routes.admin")

    resp = admin_client.request(
        method,
        f"/v1/admin/accounts/{account_id}/connections",
        headers=_headers(),
    )

    assert resp.status_code == 405
    assert resp.headers["cache-control"] == NO_STORE
    lines = [
        record.getMessage() for record in caplog.records if "admin_action" in record.getMessage()
    ]
    assert any(f"actor={ADMIN}" in line and "status_code=405" in line for line in lines), lines


def test_an_unauthenticated_unsupported_method_is_401_and_not_cached(admin_client) -> None:
    resp = admin_client.post(f"/v1/admin/accounts/{uuid4()}/connections")

    assert resp.status_code == 401
    assert resp.headers["cache-control"] == NO_STORE


def test_an_authenticated_trailing_slash_redirect_is_audited_and_not_cached(
    admin_client, caplog
) -> None:
    account_id = str(uuid4())
    caplog.set_level(logging.INFO, logger="aigateway.routes.admin")

    resp = admin_client.get(
        f"/v1/admin/accounts/{account_id}/connections/",
        headers=_headers(),
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert resp.headers["cache-control"] == NO_STORE
    lines = [
        record.getMessage() for record in caplog.records if "admin_action" in record.getMessage()
    ]
    assert any(f"actor={ADMIN}" in line and "status_code=307" in line for line in lines), lines


def test_an_unauthenticated_trailing_slash_request_is_401_and_not_cached(admin_client) -> None:
    resp = admin_client.get(
        f"/v1/admin/accounts/{uuid4()}/connections/",
        follow_redirects=False,
    )

    assert resp.status_code == 401
    assert resp.headers["cache-control"] == NO_STORE
