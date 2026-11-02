"""The admin surface manages OTHER accounts — the whole point of `OME-706`.

`OME-684` leaves a new caller authenticated but credential-less: their first request gets
`404 profile_not_found`. These routes are the operator-managed fix, so what matters here is that an
admin provisions, finds and locks out a tenant account, correctly scoped.

The admin Profile tests (key attach, masked label, tenant visibility, per-account scoping, delete,
blob removal, 404 on edit, admin-only) retired at OME-1209 Stage E3: the admin Profile routes
answer 410 `legacy_profile_api_retired` since then. Their successor is the D18 admin connection
surface, pinned by `test_admin_connections_mutation_routes.py` and
`test_admin_connections_list_route.py`; the 410 itself is pinned by
`test_legacy_profile_routes_retired.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_network

from fastapi.testclient import TestClient

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)

ADMIN = "admin@openmined.org"
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
