"""The admin surface manages OTHER accounts' credentials — the whole point of `OME-706`.

`OME-684` leaves a new caller authenticated but credential-less: their first request gets
`404 profile_not_found`. These routes are the operator-managed fix, so what matters here is that an
admin reaches a tenant's profiles at all, that the reach is CORRECTLY SCOPED (account A's admin
action never touches account B), and that the raw key never comes back out.

The persistence path itself is deliberately NOT re-tested here — `/v1/admin/.../api-key` delegates
to the same `upsert_api_key_profile` that `test_api_key_routes.py` already pins, including the
OME-307 transaction ordering. Duplicating those assertions would create a second place for them to
drift. What IS pinned here is that the delegation passes the right account through.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from ipaddress import ip_network

from fastapi.testclient import TestClient

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.profile_models import credential_name_for
from aigateway.plugins.anthropic_provider.auth import credential_service_for

ADMIN = "admin@openmined.org"
ANTHROPIC_KEY = "sk-ant-api03-admin-attached-5678"
POD_NETWORK = ip_network("10.0.0.0/8")


@dataclass
class _StubValidationService:
    """Accept any key without calling the provider.

    Deliberately NOT the `_legacy_api_key_validation_success` autouse fixture in conftest: that one
    is gated on an explicit allowlist of "frozen pre-OME-307 modules", and adding this module to it
    would violate the invariant that comment states. Swapping
    `app.state.api_key_validation_service` is what post-OME-307 tests do.

    Validation itself is already pinned by `test_profile_api_key_validation.py`; what this module
    is about is which ACCOUNT the write lands on.
    """

    result: ApiKeyValidationResult

    async def validate(self, _plugin, _provider: str, _api_key: str) -> ApiKeyValidationResult:
        return self.result


def _admin(client) -> TestClient:
    """The app in header mode with `ADMIN` allowlisted, addressed from a trusted peer."""
    client.app.state.settings.auth_mode = "cloudflare_headers"
    client.app.state.settings.allowed_networks = (POD_NETWORK,)
    client.app.state.settings.admin_emails = frozenset({ADMIN})
    client.app.state.api_key_validation_service = _StubValidationService(
        ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID,
            stage=ApiKeyValidationStage.READINESS,
        )
    )
    return TestClient(client.app, client=("10.1.2.3", 50000))


def _headers() -> dict[str, str]:
    return {"X-User-Email": ADMIN}


def _create_account(admin_client, email: str) -> str:
    resp = admin_client.post("/v1/admin/accounts", json={"email": email}, headers=_headers())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _put_key(admin_client, account_id: str, provider: str, name: str, key: str):
    return admin_client.put(
        f"/v1/admin/accounts/{account_id}/profiles/{provider}/{name}/api-key",
        json={"api_key": key},
        headers=_headers(),
    )


# --- accounts ---------------------------------------------------------------------------------


def test_an_admin_provisions_a_tenant_ahead_of_their_first_request(client) -> None:
    admin_client = _admin(client)

    resp = admin_client.post(
        "/v1/admin/accounts",
        json={"email": "Newcomer@OpenMined.org", "display_name": "Newcomer"},
        headers=_headers(),
    )

    assert resp.status_code == 201
    # Normalised exactly as `cloudflare_identity` will when they actually arrive — otherwise the
    # pre-created row and the auto-created one would be two different accounts.
    assert resp.json()["username"] == "newcomer@openmined.org"
    assert resp.json()["display_name"] == "Newcomer"


def test_creating_an_existing_tenant_is_idempotent(client) -> None:
    """Not 409. The account WILL exist the moment its owner sends a request, so "already exists"
    is not an error an operator can act on — it is the state they were trying to reach.
    """
    admin_client = _admin(client)
    first = _create_account(admin_client, "twice@openmined.org")

    resp = admin_client.post(
        "/v1/admin/accounts", json={"email": "twice@openmined.org"}, headers=_headers()
    )

    assert resp.status_code == 201
    assert resp.json()["id"] == first


def test_an_address_that_is_not_an_address_is_refused(client) -> None:
    """A typo here creates an account keyed on a string Envoy will never send — unreachable, and
    indistinguishable in the console from a real one.
    """
    resp = _admin(client).post(
        "/v1/admin/accounts", json={"email": "notanemail"}, headers=_headers()
    )

    assert resp.status_code == 422


def test_the_list_can_be_searched(client) -> None:
    admin_client = _admin(client)
    _create_account(admin_client, "findme@openmined.org")
    _create_account(admin_client, "other@openmined.org")

    resp = admin_client.get("/v1/admin/accounts", params={"q": "findme"}, headers=_headers())

    assert [a["username"] for a in resp.json()["accounts"]] == ["findme@openmined.org"]


def test_the_total_counts_matches_not_the_page(client) -> None:
    """The console pages on `total`; returning the page length would break its pagination."""
    admin_client = _admin(client)
    for i in range(3):
        _create_account(admin_client, f"paged{i}@openmined.org")

    resp = admin_client.get(
        "/v1/admin/accounts", params={"q": "paged", "limit": 1}, headers=_headers()
    )

    assert len(resp.json()["accounts"]) == 1
    assert resp.json()["total"] == 3


def test_deactivating_a_tenant_locks_them_out(client) -> None:
    """The lockout mechanism, and the reason there is no DELETE.

    `account_for_identity` returns None for an inactive account, so the tenant's next request is a
    401 — reversibly, without cascading their oauth_connections or orphaning credential blobs.
    """
    admin_client = _admin(client)
    account_id = _create_account(admin_client, "locked@openmined.org")

    patch = admin_client.patch(
        f"/v1/admin/accounts/{account_id}", json={"is_active": False}, headers=_headers()
    )

    assert patch.status_code == 200
    assert patch.json()["is_active"] is False
    locked_out = admin_client.get("/v1/auth/me", headers={"X-User-Email": "locked@openmined.org"})
    assert locked_out.status_code == 401


def test_an_unknown_account_is_not_found(client) -> None:
    resp = _admin(client).get(
        "/v1/admin/accounts/00000000-0000-0000-0000-0000000000ff", headers=_headers()
    )

    assert resp.status_code == 404


# --- profiles ---------------------------------------------------------------------------------


def test_an_admin_attaches_a_key_to_someone_elses_account(client, credential_blobs) -> None:
    """THE feature. An operator closes the credential gap for a tenant who cannot do it themselves.

    The blob is read back through the same probe the tenant-facing tests use, decrypting with the
    app's master key — so this asserts the key landed in the TENANT's slot, not the admin's.
    """
    admin_client = _admin(client)
    account_id = _create_account(admin_client, "needs-a-key@openmined.org")

    resp = _put_key(admin_client, account_id, "anthropic", "default", ANTHROPIC_KEY)

    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "authenticated"
    assert resp.json()["auth_type"] == "api_key"

    service = credential_service_for(credential_name_for(account_id, "default"))
    blob = credential_blobs.read(service, "default")
    assert blob is not None
    assert json.loads(blob) == {"auth_type": "api_key", "api_key": ANTHROPIC_KEY}


def test_the_raw_key_is_never_echoed_back(client, credential_blobs) -> None:
    """Only the masked last-4 label leaves the gateway.

    A console cannot render, log or leak what it never receives.
    """
    admin_client = _admin(client)
    account_id = _create_account(admin_client, "masked@openmined.org")

    resp = _put_key(admin_client, account_id, "anthropic", "default", ANTHROPIC_KEY)

    assert ANTHROPIC_KEY not in resp.text
    assert resp.json()["account_label"].endswith(ANTHROPIC_KEY[-4:])


def test_the_tenant_then_sees_the_profile_as_their_own(client, credential_blobs) -> None:
    """End to end: the admin writes, the TENANT reads. This is the 404-to-working transition."""
    admin_client = _admin(client)
    email = "tenant-view@openmined.org"
    account_id = _create_account(admin_client, email)
    _put_key(admin_client, account_id, "anthropic", "default", ANTHROPIC_KEY)

    as_tenant = admin_client.get("/v1/auth/profiles", headers={"X-User-Email": email})

    assert as_tenant.status_code == 200
    assert [p["name"] for p in as_tenant.json()["profiles"]] == ["default"]


def test_a_key_written_for_one_tenant_does_not_appear_for_another(client, credential_blobs) -> None:
    """Scoping. The admin route takes the account from the PATH, so passing the wrong one through
    the delegation would be invisible except here.
    """
    admin_client = _admin(client)
    alice = _create_account(admin_client, "alice-iso@openmined.org")
    bob = _create_account(admin_client, "bob-iso@openmined.org")

    _put_key(admin_client, alice, "anthropic", "default", ANTHROPIC_KEY)

    bobs = admin_client.get(f"/v1/admin/accounts/{bob}/profiles", headers=_headers())
    assert bobs.json()["profiles"] == []
    alices = admin_client.get(f"/v1/admin/accounts/{alice}/profiles", headers=_headers())
    assert [p["name"] for p in alices.json()["profiles"]] == ["default"]


def test_an_admin_deletes_a_tenants_profile(client, credential_blobs) -> None:
    admin_client = _admin(client)
    account_id = _create_account(admin_client, "revoked@openmined.org")
    _put_key(admin_client, account_id, "anthropic", "default", ANTHROPIC_KEY)

    resp = admin_client.delete(
        f"/v1/admin/accounts/{account_id}/profiles/anthropic/default", headers=_headers()
    )

    assert resp.status_code == 204
    listed = admin_client.get(f"/v1/admin/accounts/{account_id}/profiles", headers=_headers())
    assert listed.json()["profiles"] == []


def test_deleting_a_profile_removes_the_stored_credential(client, credential_blobs) -> None:
    """A committed delete must not leave an orphaned blob — encrypted key material with no profile
    pointing at it, invisible to every listing.
    """
    admin_client = _admin(client)
    account_id = _create_account(admin_client, "orphan-check@openmined.org")
    _put_key(admin_client, account_id, "anthropic", "default", ANTHROPIC_KEY)
    service = credential_service_for(credential_name_for(account_id, "default"))
    assert credential_blobs.read(service, "default") is not None

    admin_client.delete(
        f"/v1/admin/accounts/{account_id}/profiles/anthropic/default", headers=_headers()
    )

    assert credential_blobs.read(service, "default") is None


def test_editing_a_profile_that_does_not_exist_is_not_found(client) -> None:
    admin_client = _admin(client)
    account_id = _create_account(admin_client, "no-profile@openmined.org")

    resp = admin_client.patch(
        f"/v1/admin/accounts/{account_id}/profiles/anthropic/nope",
        json={"account_label": "x"},
        headers=_headers(),
    )

    assert resp.status_code == 404


def test_profile_routes_are_admin_only(client) -> None:
    """The tenant themselves must not reach the admin surface for their OWN account either.

    Otherwise `/v1/admin` would be a second, unaudited path to the tenant-facing operations.
    """
    admin_client = _admin(client)
    email = "self-serve@openmined.org"
    account_id = _create_account(admin_client, email)

    resp = admin_client.get(
        f"/v1/admin/accounts/{account_id}/profiles", headers={"X-User-Email": email}
    )

    assert resp.status_code == 403
