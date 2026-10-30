"""No grant or no key means no upstream I/O; cleanup survives disable and revoke.

# FEATURE: hosted BYOM Unit 0 — every entry point that can reach an endpoint (admin attach, self
# attach/replace, standalone validate, chat) asks the access policy first, for the account the
# operation is FOR; disconnects never ask, so a revoked or disabled pair can still be removed.
# INVARIANT: a denied endpoint answers these entry points exactly like a provider that does not
# exist, so they add no signal of their own. It hides the endpoint from the working catalog, not
# its existence: the community cache shares endpoint IDs and answers on purpose.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

from .conftest import (
    Harness,
    chat,
    delete_pair,
    put_key,
    tenant_headers,
)
from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    ENDPOINT_A,
    ENDPOINT_B,
    two_endpoint_document,
)

ABSENT = "byom_" + "f" * 32
KEY = "sk-byom-access-key-0001"


def _self_create(client: TestClient, account: str, provider: str) -> httpx.Response:
    return client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": provider, "api_key": KEY},
        headers=tenant_headers(account),
    )


def _validate(client: TestClient, account: str, provider: str) -> httpx.Response:
    return client.post(
        "/v1/oauth/connections/api-key/validate",
        json={"provider": provider, "api_key": KEY},
        headers=tenant_headers(account),
    )


# Per-request correlation ids differ on every response, whatever the provider.
_PER_REQUEST = frozenset({"trace_id", "gateway_call_id"})


def _comparable(value: Any, provider: str) -> Any:
    if isinstance(value, dict):
        return {k: _comparable(v, provider) for k, v in value.items() if k not in _PER_REQUEST}
    if isinstance(value, list):
        return [_comparable(item, provider) for item in value]
    return value.replace(provider, "<provider>") if isinstance(value, str) else value


def _attempts(client: TestClient, account: str, provider: str) -> list[tuple[int, Any]]:
    """Every upstream-reaching entry point, as (status, body with the provider ID masked)."""
    responses = [
        put_key(client, account, provider, KEY),
        _self_create(client, account, provider),
        _validate(client, account, provider),
        chat(client, account, provider),
    ]
    return [(r.status_code, _comparable(r.json(), provider)) for r in responses]


def test_an_ungranted_account_reaches_no_upstream_and_learns_nothing(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        denied = _attempts(client, ACCOUNT_B, ENDPOINT_B)
        absent = _attempts(client, ACCOUNT_B, ABSENT)

    assert [status for status, _ in denied] == [404, 404, 404, 400]
    assert denied == absent
    assert byom.upstream.calls == []
    assert byom.stored_key(ACCOUNT_B, ENDPOINT_B) is None


def test_a_disabled_endpoint_reaches_no_upstream_even_for_a_granted_account(
    byom: Harness,
) -> None:
    with byom.start(two_endpoint_document(a_enabled=False)) as client:
        denied = _attempts(client, ACCOUNT_A, ENDPOINT_A)
        absent = _attempts(client, ACCOUNT_A, ABSENT)
        granted = put_key(client, ACCOUNT_A, ENDPOINT_B, KEY)

    assert denied == absent
    assert granted.status_code == 200
    assert [c.url for c in byom.upstream.calls] == [
        "https://endpoint-b.byom.test/v1/chat/completions"
    ]


def test_a_granted_pair_without_a_key_sends_nothing(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        response = chat(client, ACCOUNT_A, ENDPOINT_B)

    assert response.status_code in (404, 409), response.text
    assert byom.upstream.calls == []


def test_an_unknown_target_alias_sends_nothing(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        byom.upstream.calls.clear()
        response = chat(client, ACCOUNT_A, ENDPOINT_A, alias="absent")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_model"
    assert byom.upstream.calls == []


def test_after_a_grant_is_revoked_chat_sends_nothing_and_admin_cleanup_works(
    byom: Harness,
) -> None:
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_B, ENDPOINT_A, KEY).status_code == 200
    byom.upstream.calls.clear()

    with byom.start(two_endpoint_document(a_accounts=(ACCOUNT_A,))) as client:
        refused = chat(client, ACCOUNT_B, ENDPOINT_A)
        deleted = delete_pair(client, ACCOUNT_B, ENDPOINT_A)

    assert refused.status_code == 400
    assert byom.upstream.calls == []
    assert deleted.status_code == 204
    assert byom.stored_key(ACCOUNT_B, ENDPOINT_A) is None


def test_after_endpoints_are_disabled_owner_and_admin_cleanup_work(byom: Harness) -> None:
    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY).status_code == 200
        assert put_key(client, ACCOUNT_A, ENDPOINT_B, KEY).status_code == 200
    byom.upstream.calls.clear()

    with byom.start(two_endpoint_document(a_enabled=False, b_enabled=False)) as client:
        listing = client.get("/v1/oauth/connections", headers=tenant_headers(ACCOUNT_A))
        (own,) = [c for c in listing.json()["connections"] if c["provider"] == ENDPOINT_A]
        owner_delete = client.delete(
            f"/v1/oauth/connections/{own['id']}", headers=tenant_headers(ACCOUNT_A)
        )
        admin_delete = delete_pair(client, ACCOUNT_A, ENDPOINT_B)

    assert (owner_delete.status_code, admin_delete.status_code) == (204, 204)
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_A) is None
    assert byom.stored_key(ACCOUNT_A, ENDPOINT_B) is None
    assert byom.upstream.calls == []
