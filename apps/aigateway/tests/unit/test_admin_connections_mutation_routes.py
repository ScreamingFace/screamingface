"""PUT `.../connections/{provider}/api-key` and DELETE `.../connections/{provider}` (OME-1497, G1).

# FEATURE: OME-1138 D18 (contract §5.2, §6, §6.1, §7) — the successor's two mutations over the
# ordered pair table: attach/replace a key (200 with the neutral DTO) and disconnect (204, also on
# repeat). Body refusals are secret-safe 422s judged after authentication.
# STORY: as an operator in the Admin console, I attach or remove a tenant's provider key; a
# mistake in the request tells me what is wrong without echoing the key, and nothing is cached.
# INVARIANT: every response — success, auth refusal, 4xx, 409 and 503 — carries
# `Cache-Control: private, no-store`; the legacy Profile operations are untouched.
"""

from __future__ import annotations

import logging
from ipaddress import ip_network
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tortoise.exceptions import OperationalError

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.pending_auth import PendingAuthEntry
from aigateway.core.provider_access import PairAuthorityStore, WriteConflict
from aigateway.routes import admin_connections

ADMIN = "admin@openmined.org"
POD_NETWORK = ip_network("10.0.0.0/8")
NO_STORE = "private, no-store"
KEY = "sk-ant-api03-route-key-0001"
INVALID = {
    "code": "invalid_credential_request",
    "message": "A valid API-key request body is required.",
}
UNSUPPORTED = {"code": "unsupported_credential_fields", "message": "Only api_key is accepted."}


@pytest.fixture
def admin_client(client, valid_api_key_readiness) -> TestClient:
    client.app.state.settings.auth_mode = "cloudflare_headers"
    client.app.state.settings.allowed_networks = (POD_NETWORK,)
    client.app.state.settings.admin_emails = frozenset({ADMIN})
    return TestClient(client.app, client=("10.1.2.3", 50000))


def _headers(**extra: str) -> dict[str, str]:
    return {"X-User-Email": ADMIN, **extra}


def _tenant(admin_client: TestClient, email: str = "tenant@openmined.org") -> str:
    resp = admin_client.post("/v1/admin/accounts", json={"email": email}, headers=_headers())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _call(client: TestClient, fn: Any, *args: Any, **kwargs: Any) -> Any:
    async def run() -> Any:
        return await fn(*args, **kwargs)

    portal = client.portal
    assert portal is not None, "the base client fixture is entered"
    return portal.call(run)


def _put(admin_client: TestClient, tenant: str, provider: str = "anthropic", **kwargs: Any):
    kwargs.setdefault("headers", _headers())
    if "content" not in kwargs:
        kwargs.setdefault("json", {"api_key": KEY})
    return admin_client.put(f"/v1/admin/accounts/{tenant}/connections/{provider}/api-key", **kwargs)


def _delete(admin_client: TestClient, tenant: str, provider: str = "anthropic", **headers: str):
    return admin_client.delete(
        f"/v1/admin/accounts/{tenant}/connections/{provider}", headers=_headers(**headers)
    )


def _list(admin_client: TestClient, tenant: str) -> dict[str, Any]:
    resp = admin_client.get(f"/v1/admin/accounts/{tenant}/connections", headers=_headers())
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- success ------------------------------------------------------------------------------------


def test_put_attaches_a_key_and_answers_the_neutral_dto(client, admin_client) -> None:
    tenant = _tenant(admin_client)

    resp = _put(admin_client, tenant)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {k: body[k] for k in ("provider", "auth_type", "credential_state")} == {
        "provider": "anthropic",
        "auth_type": "api_key",
        "credential_state": "active",
    }
    assert body["masked_key_hint"] is None
    assert KEY not in resp.text
    assert resp.headers["cache-control"] == NO_STORE
    assert [c["provider"] for c in _list(admin_client, tenant)["connections"]] == ["anthropic"]


def test_a_repeated_put_keeps_one_connection(client, admin_client) -> None:
    tenant = _tenant(admin_client)

    assert _put(admin_client, tenant).status_code == 200
    assert _put(admin_client, tenant, json={"api_key": KEY + "-2"}).status_code == 200

    assert len(_list(admin_client, tenant)["connections"]) == 1


def test_delete_disconnects_and_a_repeated_delete_is_also_204(client, admin_client) -> None:
    tenant = _tenant(admin_client)
    _put(admin_client, tenant)

    first = _delete(admin_client, tenant)
    second = _delete(admin_client, tenant)

    assert (first.status_code, second.status_code) == (204, 204)
    assert first.content == b""
    assert first.headers["cache-control"] == NO_STORE
    assert _list(admin_client, tenant) == {"connections": [], "conflicts": []}


def test_a_committed_mutation_drops_only_the_pairs_pending_flows(client, admin_client) -> None:
    tenant = _tenant(admin_client)
    pending = client.app.state.pending_auth

    def entry(provider: str) -> PendingAuthEntry:
        return PendingAuthEntry(
            account_id=tenant,
            provider=provider,
            profile_name="default",
            profile_id=f"{provider}:default",
            code_verifier="v",
            redirect_uri="https://example.invalid/cb",
        )

    pending.put("this-pair", entry("anthropic"))
    pending.put("other-pair", entry("openai"))

    assert _put(admin_client, tenant).status_code == 200

    assert pending.peek("this-pair") is None
    assert pending.peek("other-pair") is not None


# --- body hygiene (§6.1) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        ("{not json", INVALID),
        ("[]", INVALID),
        ('"sk-ant-api03-route-key-0001"', INVALID),
        ("{}", INVALID),
        ('{"api_key": ""}', INVALID),
        ('{"api_key": "   "}', INVALID),
        ('{"api_key": 12345678}', INVALID),
        ('{"api_key": "sk-ant-api03-route-key-0001", "name": "work"}', UNSUPPORTED),
        ('{"api_key": "sk-ant-api03-route-key-0001", "selector": "x"}', UNSUPPORTED),
    ],
    ids=[
        "invalid-json",
        "array",
        "string",
        "missing",
        "empty",
        "blank",
        "number",
        "name",
        "selector",
    ],
)
def test_a_bad_body_is_a_static_422_that_echoes_nothing(
    client, admin_client, content, detail
) -> None:
    tenant = _tenant(admin_client)

    resp = _put(
        admin_client,
        tenant,
        content=content,
        headers=_headers(**{"Content-Type": "application/json"}),
    )

    assert resp.status_code == 422
    assert resp.json() == {"detail": detail}
    assert KEY not in resp.text
    assert "name" not in resp.text and "selector" not in resp.text
    assert resp.headers["cache-control"] == NO_STORE
    assert _list(admin_client, tenant)["connections"] == []


@pytest.mark.parametrize("defaults", [None, {"temperature": 0.1}], ids=["null", "object"])
def test_saved_defaults_keep_their_existing_refusal(client, admin_client, defaults) -> None:
    tenant = _tenant(admin_client)

    resp = _put(admin_client, tenant, json={"api_key": KEY, "defaults": defaults})

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "defaults_not_accepted"
    assert KEY not in resp.text and "temperature" not in resp.text
    assert resp.headers["cache-control"] == NO_STORE


def test_authentication_is_judged_before_the_body(client, admin_client) -> None:
    tenant = _tenant(admin_client)

    resp = _put(admin_client, tenant, content="{not json", headers={})

    assert resp.status_code == 401
    assert resp.headers["cache-control"] == NO_STORE


def test_a_too_short_key_keeps_the_existing_normalization_refusal(client, admin_client) -> None:
    tenant = _tenant(admin_client)

    resp = _put(admin_client, tenant, json={"api_key": "short"})

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_api_key"


def test_a_rejected_key_keeps_the_existing_refusal_and_writes_nothing(
    client, admin_client, monkeypatch
) -> None:
    tenant = _tenant(admin_client)

    async def invalid(_self: Any, _plugin: Any, _provider: str, _api_key: str):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.INVALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", invalid)

    resp = _put(admin_client, tenant)

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "api_key_invalid"
    assert KEY not in resp.text
    assert _list(admin_client, tenant)["connections"] == []


# --- refusals -----------------------------------------------------------------------------------


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_an_ambiguous_pair_is_a_409_pair_detail(client, admin_client, operation) -> None:
    tenant = _tenant(admin_client)
    for _ in range(2):
        connection_id = uuid4()
        _call(
            client,
            OAuthConnectionStore().create_api_key,
            account_id=tenant,
            provider="anthropic",
            label=f"api-key-{connection_id}",
            connection_id=connection_id,
        )

    resp = _put(admin_client, tenant) if operation == "put" else _delete(admin_client, tenant)

    assert resp.status_code == 409
    assert resp.json() == {
        "detail": {
            "code": "credential_pair_ambiguous",
            "message": "The provider credential cannot be addressed unambiguously.",
            "provider": "anthropic",
        }
    }
    assert resp.headers["cache-control"] == NO_STORE


@pytest.mark.parametrize(
    ("kind", "status", "detail"),
    [
        (
            "superseded",
            409,
            {
                "code": "credential_publication_superseded",
                "message": "Credential state changed. Reload before submitting another change.",
                "provider": "anthropic",
            },
        ),
        (
            "retry_exhausted",
            503,
            {
                "code": "credential_write_conflict",
                "message": "Credential update conflicted. Try again.",
                "provider": "anthropic",
            },
        ),
    ],
)
@pytest.mark.parametrize("subject", ["profile", "connection"])
def test_a_lost_write_renders_the_successor_conflict(
    client, admin_client, monkeypatch, kind, status, detail, subject
) -> None:
    tenant = _tenant(admin_client)

    async def lost(*_args: Any, **_kwargs: Any) -> Any:
        raise WriteConflict(kind, subject=subject, provider="anthropic", requested="default")

    monkeypatch.setattr(admin_connections, "set_pair_api_key", lost)
    monkeypatch.setattr(admin_connections, "delete_pair", lost)

    for resp in (_put(admin_client, tenant), _delete(admin_client, tenant)):
        assert resp.status_code == status
        assert resp.json() == {"detail": detail}
        assert resp.headers["cache-control"] == NO_STORE


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_an_unknown_provider_or_account_is_404(client, admin_client, operation) -> None:
    tenant = _tenant(admin_client)
    act = _put if operation == "put" else _delete

    unknown_provider = act(admin_client, tenant, "no-such-provider")
    unknown_account = act(admin_client, str(uuid4()))

    assert unknown_provider.status_code == 404
    assert unknown_provider.json()["detail"]["code"] == "unknown_provider"
    assert unknown_account.status_code == 404
    assert unknown_account.json()["detail"] == {"code": "account_not_found"}
    assert unknown_provider.headers["cache-control"] == NO_STORE


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_a_nonblank_x_profile_is_refused_without_echo(client, admin_client, operation) -> None:
    tenant = _tenant(admin_client)

    if operation == "put":
        resp = _put(admin_client, tenant, headers=_headers(**{"X-Profile": "work"}))
    else:
        resp = _delete(admin_client, tenant, **{"X-Profile": "work"})

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "x_profile_unsupported"
    assert "work" not in resp.text
    assert resp.headers["cache-control"] == NO_STORE


# --- audit and contract -------------------------------------------------------------------------


def test_the_audit_line_names_the_actor_and_the_final_status(client, admin_client, caplog) -> None:
    tenant = _tenant(admin_client)
    caplog.set_level(logging.INFO, logger="aigateway.routes.admin")

    _put(admin_client, tenant)
    _delete(admin_client, tenant)

    lines = [r.getMessage() for r in caplog.records if "admin_action" in r.getMessage()]
    for status in ("status_code=200", "status_code=204"):
        assert any(f"actor={ADMIN}" in line and status in line for line in lines), lines
    assert not any(KEY in line for line in lines)


def test_the_openapi_contract_declares_both_mutations_and_drops_the_legacy_ones(
    client, admin_client
) -> None:
    schema = admin_client.get("/openapi.json").json()
    paths = schema["paths"]

    put = paths["/v1/admin/accounts/{account_id}/connections/{provider}/api-key"]["put"]
    assert put["operationId"] == "set_admin_account_connection_api_key"
    assert put["security"] == [{"CloudflareUserEmail": []}]
    body = put["requestBody"]["content"]["application/json"]["schema"]
    assert body["additionalProperties"] is False
    assert body["required"] == ["api_key"]
    assert set(body["properties"]) == {"api_key"}
    assert put["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AdminConnectionOut"
    }
    delete = paths["/v1/admin/accounts/{account_id}/connections/{provider}"]["delete"]
    assert delete["operationId"] == "delete_admin_account_connection"
    assert "204" in delete["responses"]
    # The legacy Profile operations are retired (OME-1209 Stage E3): no admin Profile path, no
    # Profile schema.
    assert "/v1/admin/accounts/{account_id}/profiles/{provider}/{name}/api-key" not in paths
    assert "/v1/admin/accounts/{account_id}/profiles/{provider}/{name}" not in paths
    assert "AdminProfileOut" not in schema["components"]["schemas"]


# --- review follow-ups --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type",
    [None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"],
    ids=["absent", "text-plain", "form", "multipart"],
)
def test_a_body_without_a_json_content_type_is_refused(client, admin_client, content_type) -> None:
    # FastAPI's strict Content-Type default (0.132+): a body a browser can send cross-site
    # without a CORS preflight is never parsed as JSON — the successor keeps that protection.
    tenant = _tenant(admin_client)
    headers = _headers() if content_type is None else _headers(**{"Content-Type": content_type})

    resp = _put(admin_client, tenant, content=f'{{"api_key": "{KEY}"}}', headers=headers)

    assert resp.status_code == 422
    assert resp.json() == {"detail": INVALID}
    assert _list(admin_client, tenant)["connections"] == []


@pytest.mark.parametrize("content_type", ["application/json; charset=utf-8", "application/x+json"])
def test_a_json_content_type_with_parameters_or_a_json_suffix_is_accepted(
    client, admin_client, content_type
) -> None:
    tenant = _tenant(admin_client)

    resp = _put(
        admin_client,
        tenant,
        content=f'{{"api_key": "{KEY}"}}',
        headers=_headers(**{"Content-Type": content_type}),
    )

    assert resp.status_code == 200, resp.text


def test_the_published_request_schema_carries_no_internal_notes(client, admin_client) -> None:
    schema = admin_client.get("/openapi.json").json()
    put = schema["paths"]["/v1/admin/accounts/{account_id}/connections/{provider}/api-key"]["put"]
    body = put["requestBody"]["content"]["application/json"]["schema"]

    # Only the public description is published; internal notes stay in source comments.
    assert body["description"] == "The one API key to attach to the provider."


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_a_store_outage_during_a_mutation_is_a_scoped_503_not_a_bare_500(
    client, admin_client, monkeypatch, operation
) -> None:
    tenant = _tenant(admin_client)
    if operation == "delete":
        assert _put(admin_client, tenant).status_code == 200

    async def down(*_args: Any, **_kwargs: Any) -> Any:
        raise OperationalError("server closed the connection unexpectedly")

    monkeypatch.setattr(PairAuthorityStore, "advance", down)

    resp = _put(admin_client, tenant) if operation == "put" else _delete(admin_client, tenant)

    verb = "update" if operation == "put" else "delete"
    assert resp.status_code == 503
    assert resp.json() == {
        "detail": {
            "code": "credential_store_unavailable",
            "message": f"Could not {verb} credentials. Try again.",
        }
    }
    assert "server closed" not in resp.text
    assert resp.headers["retry-after"] == "1"
    assert resp.headers["cache-control"] == NO_STORE


MUTATION_PATHS = [
    ("connections/anthropic/api-key", "PUT"),
    ("connections/anthropic", "DELETE"),
]


@pytest.mark.parametrize(("suffix", "allowed"), MUTATION_PATHS, ids=["api-key", "pair"])
@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "PUT", "DELETE"])
def test_an_unsupported_method_is_an_audited_405_and_not_cached(
    client, admin_client, caplog, suffix, allowed, method
) -> None:
    if method == allowed:
        pytest.skip("the supported method")
    tenant = _tenant(admin_client)
    path = f"/v1/admin/accounts/{tenant}/{suffix}"
    caplog.set_level(logging.INFO, logger="aigateway.routes.admin")

    resp = admin_client.request(method, path, headers=_headers())
    anonymous = admin_client.request(method, path)

    assert resp.status_code == 405
    assert resp.headers["allow"] == allowed
    assert resp.headers["cache-control"] == NO_STORE
    assert anonymous.status_code == 401
    assert anonymous.headers["cache-control"] == NO_STORE
    lines = [r.getMessage() for r in caplog.records if "admin_action" in r.getMessage()]
    assert any(f"actor={ADMIN}" in line and "status_code=405" in line for line in lines), lines


@pytest.mark.parametrize(("suffix", "allowed"), MUTATION_PATHS, ids=["api-key", "pair"])
def test_a_trailing_slash_is_an_audited_redirect_to_the_canonical_path(
    client, admin_client, suffix, allowed
) -> None:
    tenant = _tenant(admin_client)
    path = f"/v1/admin/accounts/{tenant}/{suffix}"

    resp = admin_client.request(allowed, path + "/", headers=_headers(), follow_redirects=False)
    anonymous = admin_client.request(allowed, path + "/", follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"].endswith(path)
    assert resp.headers["cache-control"] == NO_STORE
    assert anonymous.status_code == 401
    assert anonymous.headers["cache-control"] == NO_STORE
