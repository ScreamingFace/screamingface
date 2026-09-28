"""The Profile refresh facade of a MIGRATED pair refreshes THROUGH its effective Connection (S2'b3).

# FEATURE: Stage B Target — "the Connection backing owns … refresh, error marking": for a migrated
# pair `POST …/profiles/{name}/refresh` runs the provider refresh under the locator name, touches
# the effective Connection, mirrors the document (D-S2b-2) and marks the CONNECTION on failure;
# the legacy `401 auth_required` / `409 profile_conflict` bodies stay byte for byte.
# INVARIANT (D-S2b3-5): an effective row in `error` or `pending` is never refreshed — no network
# call, no row or document mutation — the pair recovers by re-auth or key replacement.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from connection_backed_admin_probes import (
    KEY,
    admin_of,
    blob_at_profile_address,
    connection,
    document,
    marker,
)
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import (
    SENTINEL,
    access_token_of,
    status,
    use_failing_exchange,
    use_tokens,
)
from provider_access_harness import PROVIDER, ProfileBackedHarness

from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.profile_models import ProfileState, credential_name_for
from aigateway.core.provider_access import connection_facade

REAUTH = f"/v1/auth/{PROVIDER}/profiles/default"


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def refresh(harness: Any, name: str = "default") -> httpx.Response:
    return harness.client.post(f"/v1/auth/{PROVIDER}/profiles/{name}/refresh")


def use_deleting_tokens(harness: Any, token: str) -> None:
    """A token endpoint that DELETES the pair through the admin boundary before answering.

    WHY inside the handler: it runs on the app loop, inside the provider network window of the
    refresh — the exact moment H-1 says a delete must win.
    """

    async def token_handler(_request: httpx.Request) -> httpx.Response:
        await admin_of(harness).delete(harness.account_id, PROVIDER, legacy_name="default")
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "refresh_token": f"refresh-{token}",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    harness.client.app.state.anthropic_http_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(token_handler), timeout=httpx.Timeout(5.0)
    )


# --- migrated pairs ----------------------------------------------------------------------------


def test_refresh_over_a_migrated_pair_rewrites_the_locator_blob_and_touches_the_row(
    migrated,
) -> None:
    h = migrated
    h.seed_profile()  # document + Profile-addressed blob "tok" + active Connection + marker
    effective = h.migrated["default"]
    use_tokens(h, "fresh-tok")

    resp = refresh(h)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["state"], body["auth_type"]) == ("authenticated", "oauth")
    assert body["last_refreshed_at"] is not None
    assert access_token_of(blob_at_profile_address(h)) == "fresh-tok"
    row = connection(h, effective)
    assert (row.status, row.last_refreshed_at is not None) == ("active", True)
    doc = document(h)
    assert doc is not None
    assert (doc.state, doc.last_refreshed_at is not None) == (ProfileState.AUTHENTICATED, True)
    name = credential_name_for(h.account_id, "default")
    assert name in h.evicted()
    assert name in h.invalidated()
    # INVARIANT: a refresh changes no authority — the marker does not move.
    assert marker(h).generation == 1


def test_a_failed_refresh_marks_the_connection_and_mirrors_the_error(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    use_failing_exchange(h)

    resp = refresh(h)

    assert resp.status_code == 401, resp.text
    detail = resp.json()["detail"]
    assert (detail["code"], detail["reauth_url"]) == ("auth_required", REAUTH)
    assert detail["message"]
    assert SENTINEL not in resp.text
    row = connection(h, effective)
    assert (row.status, row.label) == ("error", f"error:{effective}")
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.ERROR
    assert status(h).json()["state"] == "error"
    name = credential_name_for(h.account_id, "default")
    assert name in h.evicted()
    assert name in h.invalidated()
    assert marker(h).generation == 1


def test_a_refresh_whose_window_saw_the_pair_deleted_resurrects_nothing(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    use_deleting_tokens(h, "fresh-tok")

    resp = refresh(h)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == {
        "code": "profile_conflict",
        "provider": PROVIDER,
        "profile": "default",
    }
    assert document(h) is None
    assert connection(h, effective).status == "revoked"
    pair = marker(h)
    assert (pair.migration_state, pair.effective_connection_id) == ("migrated", None)
    assert status(h).status_code == 404


def test_an_errored_effective_row_is_not_refreshed(migrated) -> None:
    h = migrated
    h.seed_profile(state=ProfileState.ERROR)
    effective = h.migrated["default"]
    before = connection(h, effective)
    use_tokens(h, "fresh-tok")

    resp = refresh(h)

    assert resp.status_code == 401, resp.text
    detail = resp.json()["detail"]
    assert (detail["code"], detail["reauth_url"]) == ("auth_required", REAUTH)
    # INVARIANT: no network call, no mutation — the blob, the row and the document are as seeded.
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    after = connection(h, effective)
    assert (after.status, after.label, after.last_refreshed_at) == (
        "error",
        before.label,
        before.last_refreshed_at,
    )
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.ERROR


def test_a_pending_effective_row_is_not_refreshed(migrated) -> None:
    h = migrated
    h.seed_profile(state=ProfileState.PENDING)
    effective = h.migrated["default"]
    use_tokens(h, "fresh-tok")

    resp = refresh(h)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "auth_required"
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    assert connection(h, effective).status == "pending"
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.PENDING


def test_refresh_of_a_migrated_api_key_pair_validates_the_stored_key(migrated) -> None:
    h = migrated
    h.seed_profile(auth_type="api_key", credential=KEY)
    effective = h.migrated["default"]

    resp = refresh(h)

    assert resp.status_code == 200, resp.text
    assert (resp.json()["state"], resp.json()["auth_type"]) == ("authenticated", "api_key")
    row = connection(h, effective)
    assert (row.status, row.auth_type, row.last_refreshed_at is not None) == (
        "active",
        "api_key",
        True,
    )


def test_a_failure_whose_row_was_revoked_in_the_window_marks_nothing(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    store = OAuthConnectionStore()

    async def token_handler(_request: httpx.Request) -> httpx.Response:
        # A Connection-native revoke lands during the provider network window, then the
        # provider rejects the refresh token.
        row = await store.get(h.account_id, effective)
        assert row is not None
        await store.mark_revoked(row)
        return httpx.Response(400, json={"error": "invalid_grant", "detail": SENTINEL})

    h.client.app.state.anthropic_http_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(token_handler), timeout=httpx.Timeout(5.0)
    )

    resp = refresh(h)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "auth_required"
    assert SENTINEL not in resp.text
    # INVARIANT: `mark_error` is fenced on `active` — a revoked row is not re-marked, and the
    # document is not mirrored to ERROR on the strength of a mark that did not happen.
    assert connection(h, effective).status == "revoked"
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.AUTHENTICATED


def test_refresh_is_400_when_the_provider_has_no_strategy_for_the_row(
    migrated, monkeypatch
) -> None:
    h = migrated
    h.seed_profile()
    monkeypatch.setattr(
        connection_facade, "credential_strategy_for_connection", lambda *_a, **_k: None
    )

    resp = refresh(h)

    assert resp.status_code == 400
    assert resp.json()["detail"] == {"code": "provider_does_not_use_oauth"}
    assert access_token_of(blob_at_profile_address(h)) == "tok"


def test_refresh_is_404_when_a_migrated_pair_has_no_document(migrated) -> None:
    h = migrated
    h.seed_authority()  # a Connection-only migrated pair: nothing for the facade to show

    resp = refresh(h)

    assert resp.status_code == 404
    assert resp.json()["detail"] == {"code": "profile_not_found"}


# --- unmigrated pairs --------------------------------------------------------------------------


def test_refresh_of_an_unmigrated_pair_keeps_the_legacy_body(legacy) -> None:
    h = legacy
    h.seed_profile()
    use_tokens(h, "fresh-tok")

    resp = refresh(h)

    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "authenticated"
    assert access_token_of(blob_at_profile_address(h)) == "fresh-tok"
    pair = marker(h)
    assert (pair.migration_state, pair.generation) == ("none", 0)
