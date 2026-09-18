"""The Profile management routes as SHELLS over `ProviderCredentialAdmin` (OME-1230, Stage A3).

# FEATURE: OME-1138 — the tenant and admin PUT/DELETE/listing routes no longer own their bodies;
# they validate, call the boundary, render its refusals and return its projection.
# INVARIANT: HTTP status codes and bodies are byte-identical to 248b0b6d. What moved is WHERE the
# body lives, proven here by swapping the boundary for a recording fake and watching the routes
# talk to it — a route that still reached the index directly would not.
# INVARIANT (F4, owner 2026-09-18): key validation stays in the shell and runs BEFORE the boundary
# is called; (edge half) the post-commit OAuth cleanup stays in the shell too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import ip_network
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from aigateway.core.admin_schemas import AdminProfileList, AdminProfileOut
from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.pending_auth import PendingAuthEntry
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileDefaults, ProfileState, profile_id_for
from aigateway.core.provider_access import (
    CredentialStoreUnavailable,
    CredentialSummary,
    ProviderAccessRefusal,
    ProviderUnknown,
    TargetMissing,
    WriteConflict,
)

KEY = "sk-ant-api03-shell-key-7777"
ADMIN = "admin@openmined.org"


@dataclass
class _ValidationStub:
    result: ApiKeyValidationResult

    async def validate(self, _plugin: Any, _provider: str, _api_key: str) -> ApiKeyValidationResult:
        return self.result


def _valid() -> _ValidationStub:
    return _ValidationStub(
        ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )
    )


def _invalid() -> _ValidationStub:
    return _ValidationStub(
        ApiKeyValidationResult(
            state=ApiKeyValidationState.INVALID, stage=ApiKeyValidationStage.AUTHENTICATION
        )
    )


def _summary(account_id: str, provider: str, name: str, **overrides: Any) -> CredentialSummary:
    projection = {
        "id": profile_id_for(account_id, provider, name),
        "account_id": account_id,
        "provider": provider,
        "name": name,
        "account_label": "API key ····7777",
        "scopes": [],
        "last_refreshed_at": "2026-09-18T12:00:00Z",
        "state": "authenticated",
        "auth_type": "api_key",
        "defaults": ProfileDefaults().model_dump(mode="json"),
        **overrides,
    }
    return CredentialSummary(
        provider, name, "api_key", "authenticated", legacy_projection=projection
    )


@dataclass
class _RecordingAdmin:
    """A boundary that records what the shells ask of it and answers canned summaries."""

    account_id: str
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)
    refusal: ProviderAccessRefusal | None = None
    listing: tuple[CredentialSummary, ...] = ()

    async def list(
        self, account_id: str, provider: str | None = None
    ) -> tuple[CredentialSummary, ...]:
        self.calls.append(("list", (account_id, provider), {}))
        self._refuse()
        return tuple(s for s in self.listing if provider is None or s.provider == provider)

    async def set_api_key(self, account_id: str, provider: str, **kwargs: Any) -> CredentialSummary:
        self.calls.append(("set_api_key", (account_id, provider), kwargs))
        self._refuse()
        return _summary(account_id, provider, kwargs["legacy_name"] or "default")

    async def delete(self, account_id: str, provider: str, **kwargs: Any) -> None:
        self.calls.append(("delete", (account_id, provider), kwargs))
        self._refuse()

    def _refuse(self) -> None:
        if self.refusal is not None:
            raise self.refusal


@pytest.fixture
def tenant(authenticated_client, credential_blobs):
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    fake = _RecordingAdmin(account_id)
    authenticated_client.app.state.provider_credential_admin = fake
    authenticated_client.app.state.api_key_validation_service = _valid()
    return authenticated_client, fake


def _admin_client(client) -> TestClient:
    client.app.state.settings.auth_mode = "cloudflare_headers"
    client.app.state.settings.allowed_networks = (ip_network("10.0.0.0/8"),)
    client.app.state.settings.admin_emails = frozenset({ADMIN})
    client.app.state.api_key_validation_service = _valid()
    return TestClient(client.app, client=("10.1.2.3", 50000), headers={"X-User-Email": ADMIN})


def _create_account(admin: TestClient) -> str:
    response = admin.post(
        "/v1/admin/accounts", json={"email": f"tenant-{uuid4().hex[:8]}@openmined.org"}
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


# --- the tenant shells delegate ------------------------------------------------------------


def test_the_tenant_put_validates_then_calls_the_boundary_and_returns_its_projection(
    tenant,
) -> None:
    client, fake = tenant

    resp = client.put(
        "/v1/auth/anthropic/profiles/keyed/api-key",
        json={"api_key": f"  {KEY}  ", "defaults": {"max_tokens": 512}},
    )

    assert resp.status_code == 200, resp.text
    assert fake.calls == [
        (
            "set_api_key",
            (fake.account_id, "anthropic"),
            {
                "raw_api_key": KEY,
                "legacy_name": "keyed",
                "defaults": ProfileDefaults(max_tokens=512),
            },
        )
    ]
    assert resp.json() == _summary(fake.account_id, "anthropic", "keyed").legacy_projection


def test_the_tenant_put_passes_omitted_defaults_through_as_none(tenant) -> None:
    client, fake = tenant

    client.put("/v1/auth/anthropic/profiles/keyed/api-key", json={"api_key": KEY})

    assert fake.calls[0][2]["defaults"] is None


def test_the_shell_refuses_an_invalid_key_before_reaching_the_boundary(tenant) -> None:
    client, fake = tenant
    client.app.state.api_key_validation_service = _invalid()

    resp = client.put("/v1/auth/anthropic/profiles/keyed/api-key", json={"api_key": KEY})

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "api_key_invalid"
    assert fake.calls == []


def test_the_shell_still_refuses_a_short_key_and_an_unknown_provider_itself(tenant) -> None:
    client, fake = tenant

    short = client.put("/v1/auth/anthropic/profiles/keyed/api-key", json={"api_key": "short"})
    unknown = client.put("/v1/auth/nope/profiles/keyed/api-key", json={"api_key": KEY})

    assert (short.status_code, short.json()["detail"]["code"]) == (400, "invalid_api_key")
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == {"code": "unknown_provider", "provider": "nope"}
    assert fake.calls == []


def test_the_tenant_put_pops_the_pending_oauth_flow_after_the_boundary_commits(tenant) -> None:
    client, fake = tenant
    pending = client.app.state.pending_auth
    pending.put(
        "stale-state",
        PendingAuthEntry(
            account_id=fake.account_id,
            provider="anthropic",
            profile_name="keyed",
            profile_id=profile_id_for(fake.account_id, "anthropic", "keyed"),
            code_verifier="v",
            redirect_uri="http://localhost/cb",
        ),
    )

    resp = client.put("/v1/auth/anthropic/profiles/keyed/api-key", json={"api_key": KEY})

    assert resp.status_code == 200
    assert pending.pop_for_profile(fake.account_id, "anthropic", "keyed") == []


def test_the_tenant_delete_calls_the_boundary_with_the_legacy_name(tenant) -> None:
    client, fake = tenant

    resp = client.delete("/v1/auth/anthropic/profiles/keyed")

    assert resp.status_code == 204
    assert fake.calls == [("delete", (fake.account_id, "anthropic"), {"legacy_name": "keyed"})]


@pytest.mark.parametrize(
    ("refusal", "status", "detail"),
    [
        (ProviderUnknown("anthropic"), 404, {"code": "unknown_provider", "provider": "anthropic"}),
        (
            CredentialStoreUnavailable("API-key credentials"),
            503,
            {
                "code": "credential_store_unavailable",
                "message": "Could not store API-key credentials. Try again.",
            },
        ),
        (
            WriteConflict("retry_exhausted", subject="profile"),
            503,
            {
                "code": "profile_index_conflict",
                "message": "Profile metadata update conflicted. Try again.",
            },
        ),
        (
            WriteConflict("superseded", subject="profile", provider="anthropic", requested="keyed"),
            409,
            {"code": "profile_conflict", "provider": "anthropic", "profile": "keyed"},
        ),
    ],
    ids=["unknown_provider", "store_unavailable", "retry_exhausted", "superseded"],
)
def test_the_put_shell_renders_each_boundary_refusal_as_todays_response(
    tenant, refusal: ProviderAccessRefusal, status: int, detail: dict
) -> None:
    client, fake = tenant
    fake.refusal = refusal

    resp = client.put("/v1/auth/anthropic/profiles/keyed/api-key", json={"api_key": KEY})

    assert resp.status_code == status
    assert resp.json()["detail"] == detail


@pytest.mark.parametrize(
    ("refusal", "detail"),
    [
        (ProviderUnknown("anthropic"), {"code": "unknown_provider"}),
        (TargetMissing("anthropic", "keyed"), {"code": "profile_not_found"}),
    ],
    ids=["unknown_provider", "profile_not_found"],
)
def test_the_delete_shell_keeps_its_provider_less_404_bodies(tenant, refusal, detail) -> None:
    client, fake = tenant
    fake.refusal = refusal

    resp = client.delete("/v1/auth/anthropic/profiles/keyed")

    assert resp.status_code == 404
    assert resp.json()["detail"] == detail


def test_the_tenant_listings_render_the_boundary_projection(tenant) -> None:
    client, fake = tenant
    fake.listing = (
        _summary(fake.account_id, "anthropic", "keyed"),
        _summary(fake.account_id, "gemini", "g", account_label="API key ····0001"),
    )

    everything = client.get("/v1/auth/profiles")
    gemini = client.get("/v1/auth/gemini/profiles")
    one = client.get("/v1/auth/anthropic/profiles/keyed")
    missing = client.get("/v1/auth/anthropic/profiles/absent")

    assert everything.json() == {"profiles": [s.legacy_projection for s in fake.listing]}
    assert gemini.json() == {"profiles": [fake.listing[1].legacy_projection]}
    assert one.json() == fake.listing[0].legacy_projection
    assert missing.status_code == 404
    assert missing.json()["detail"] == {
        "code": "profile_not_found",
        "provider": "anthropic",
        "name": "absent",
    }
    assert [c[0] for c in fake.calls] == ["list", "list", "list", "list"]
    assert fake.calls[1][1] == (fake.account_id, "gemini")


# --- the admin shells delegate on the tenant's behalf ----------------------------------------


def test_the_admin_shells_address_the_tenant_account_through_the_boundary(
    client, credential_blobs
) -> None:
    admin = _admin_client(client)
    tenant_id = _create_account(admin)
    fake = _RecordingAdmin(tenant_id)
    client.app.state.provider_credential_admin = fake
    fake.listing = (_summary(tenant_id, "anthropic", "default"),)

    put = admin.put(
        f"/v1/admin/accounts/{tenant_id}/profiles/anthropic/default/api-key", json={"api_key": KEY}
    )
    listed = admin.get(f"/v1/admin/accounts/{tenant_id}/profiles")
    deleted = admin.delete(f"/v1/admin/accounts/{tenant_id}/profiles/anthropic/default")

    assert put.status_code == 200, put.text
    assert put.json() == AdminProfileOut.model_validate(
        fake.listing[0].legacy_projection
    ).model_dump(mode="json")
    assert KEY not in put.text
    assert listed.status_code == 200
    assert listed.json() == AdminProfileList(
        profiles=[AdminProfileOut.model_validate(s.legacy_projection) for s in fake.listing]
    ).model_dump(mode="json")
    assert deleted.status_code == 204
    assert [(c[0], c[1][0]) for c in fake.calls] == [
        ("set_api_key", tenant_id),
        ("list", tenant_id),
        ("delete", tenant_id),
    ]
    assert fake.calls[0][2] == {"raw_api_key": KEY, "legacy_name": "default", "defaults": None}
    assert fake.calls[2][2] == {"legacy_name": "default"}


# --- listing parity over the REAL boundary -----------------------------------------------------


@pytest.mark.asyncio
async def test_the_tenant_and_admin_listings_are_byte_identical_to_the_index_rows(
    authenticated_client, credential_blobs
) -> None:
    """Parity over the real Profile-backed boundary: the JSON a client sees is today's JSON."""
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    seeded = [
        Profile(
            id=profile_id_for(account_id, "anthropic", "work"),
            account_id=account_id,
            provider="anthropic",
            name="work",
            state=ProfileState.AUTHENTICATED,
            auth_type="oauth",
            account_label="user@example.com",
            scopes=["org:create_api_key"],
            defaults=ProfileDefaults(model="anthropic/claude-sonnet-4-5", temperature=0.1),
        ),
        Profile(
            id=profile_id_for(account_id, "gemini", "default"),
            account_id=account_id,
            provider="gemini",
            name="default",
            state=ProfileState.PENDING,
        ),
    ]
    for profile in seeded:
        await idx.upsert(profile)
    stored = await idx.list(account_id)

    everything = authenticated_client.get("/v1/auth/profiles")
    gemini = authenticated_client.get("/v1/auth/gemini/profiles")
    one = authenticated_client.get("/v1/auth/anthropic/profiles/work")

    assert everything.json() == {"profiles": [p.model_dump(mode="json") for p in stored]}
    assert gemini.json() == {
        "profiles": [p.model_dump(mode="json") for p in stored if p.provider == "gemini"]
    }
    assert one.json() == next(p for p in stored if p.name == "work").model_dump(mode="json")

    admin = _admin_client(authenticated_client)
    listed = admin.get(f"/v1/admin/accounts/{account_id}/profiles")
    assert listed.status_code == 200, listed.text
    assert listed.json() == AdminProfileList(
        profiles=[AdminProfileOut.model_validate(p, from_attributes=True) for p in stored]
    ).model_dump(mode="json")
