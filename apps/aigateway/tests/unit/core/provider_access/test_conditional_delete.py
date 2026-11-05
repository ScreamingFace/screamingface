"""A Connection delete that requires the row's status (OME-1138 close-out, L7c).

# FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §2a —
# `DELETE /v1/oauth/connections/{id}?expected_status=pending|error` removes the row only while it
# still has that status and is not its pair's effective reference; otherwise 409
# `connection_conflict`, and the delete's whole transaction (its pair claim included) rolls back.
# STORY: as a Local Engine user, a sign-in or key fix I finish while the Engine repairs its rows is
# never deleted by that repair.
# INVARIANT: without the parameter the delete is unchanged — it removes a row of any status.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from connection_backed_admin_probes import (
    KEY,
    blob_at_connection_address,
    blob_at_name_address,
    connection,
    marker,
)
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import access_token_of
from provider_access_harness import PROVIDER

from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.provider_access.pair_authority import UNMARKED_GENERATION
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from tests.unit.seed_state import SeedState


@pytest.fixture
def h(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def delete(h: Any, connection_id: str, expected_status: str | None) -> httpx.Response:
    params = {} if expected_status is None else {"expected_status": expected_status}
    return h.client.delete(f"/v1/oauth/connections/{connection_id}", params=params)


def pending_row(h: Any, label: str = "screamingface") -> str:
    """A sign-in that has not finished: a `pending` row with no credential yet."""
    row = h.call(
        OAuthConnectionStore().create_pending,
        account_id=h.account_id,
        provider=PROVIDER,
        label=label,
        connection_id=uuid4(),
    )
    return str(row.id)


def finish_sign_in(h: Any, connection_id: str) -> None:
    """What the OAuth callback commits: the `pending` row turns `active` and gets its blob."""

    async def complete() -> None:
        store = OAuthConnectionStore()
        row = await store.get(h.account_id, connection_id)
        assert row is not None
        assert await store.complete_pending(row, label=row.label, identity=None) is not None

    h.call(complete)
    h.blobs.write(
        _connection_service(h, connection_id),
        "default",
        '{"access_token": "fresh", "refresh_token": "rt", "token_type": "Bearer"}',
    )


def errored_key_row(h: Any, label: str = "screamingface") -> str:
    """An API-key row whose key the provider rejected: `error`, its blob still stored."""
    connection_id = h.seed_connection(label=label, auth_type="api_key")

    async def reject() -> None:
        store = OAuthConnectionStore()
        row = await store.get(h.account_id, connection_id)
        assert row is not None
        assert await store.mark_error(row, "key rejected") is not None

    h.call(reject)
    return connection_id


def _connection_service(h: Any, connection_id: str) -> str:
    return credential_service_for(credential_key_for(h.account_id, connection_id))


def assert_refused(resp: httpx.Response) -> None:
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "connection_conflict"


# --- the row still has the expected status: removed ----------------------------------------


def test_a_row_still_pending_is_removed(h) -> None:
    pending = pending_row(h)

    resp = delete(h, pending, "pending")

    assert resp.status_code == 204, resp.text
    assert connection(h, pending).status == "revoked"
    assert credential_key_for(h.account_id, pending) in h.evicted()


def test_a_row_still_in_error_is_removed_with_its_blob(h) -> None:
    errored = errored_key_row(h)
    assert blob_at_connection_address(h, errored) is not None

    resp = delete(h, errored, "error")

    assert resp.status_code == 204, resp.text
    assert connection(h, errored).status == "revoked"
    assert blob_at_connection_address(h, errored) is None


# --- the row moved since the caller listed it: refused, nothing changes ---------------------


def test_a_sign_in_finished_since_the_listing_keeps_its_row(h) -> None:
    # WHY the unmarked pair: the delete claims it (generation 0 → 1) before the status check, so
    # an unchanged generation proves the refusal rolled the claim back with everything else.
    pending = pending_row(h)
    finish_sign_in(h, pending)

    resp = delete(h, pending, "pending")

    assert_refused(resp)
    assert connection(h, pending).status == "active"
    assert access_token_of(blob_at_connection_address(h, pending)) == "fresh"
    assert marker(h).generation == UNMARKED_GENERATION
    assert credential_key_for(h.account_id, pending) not in h.evicted()


def test_a_key_fixed_since_the_listing_keeps_its_row(h, valid_api_key_readiness) -> None:
    errored = errored_key_row(h)
    fixed = h.client.put(f"/v1/oauth/connections/{errored}/api-key", json={"api_key": KEY})
    assert fixed.status_code == 200, fixed.text
    generation = marker(h).generation

    resp = delete(h, errored, "error")

    assert_refused(resp)
    assert connection(h, errored).status == "active"
    assert blob_at_connection_address(h, errored) is not None
    assert marker(h).generation == generation


def test_a_row_in_another_unusable_status_is_refused(h) -> None:
    errored = errored_key_row(h)

    resp = delete(h, errored, "pending")

    assert_refused(resp)
    assert connection(h, errored).status == "error"
    assert blob_at_connection_address(h, errored) is not None


@pytest.mark.parametrize(
    ("state", "auth_type", "expected_status"),
    [(SeedState.PENDING, "oauth", "pending"), (SeedState.ERROR, "api_key", "error")],
)
def test_the_effective_row_is_never_removed_by_a_conditional_delete(
    h, state: SeedState, auth_type: str, expected_status: str
) -> None:
    # INVARIANT: a conditional delete removes a row that serves nothing; the row chat uses is
    # removed only by a plain delete, the user's explicit intent.
    h.seed_credential(state=state, auth_type=auth_type)
    effective = h.migrated["default"]
    before = marker(h)

    resp = delete(h, effective, expected_status)

    assert_refused(resp)
    assert connection(h, effective).status == expected_status
    after = marker(h)
    assert (after.generation, after.effective_connection_id) == (
        before.generation,
        before.effective_connection_id,
    )
    assert blob_at_name_address(h) is not None


# --- unchanged answers --------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["pending", "active"])
def test_without_the_parameter_a_row_of_any_status_is_removed(h, status: str) -> None:
    row = pending_row(h) if status == "pending" else h.seed_connection(label="screamingface")

    resp = delete(h, row, None)

    assert resp.status_code == 204, resp.text
    assert connection(h, row).status == "revoked"


@pytest.mark.parametrize("value", ["active", "expired", "revoked", "PENDING", "stale", ""])
def test_the_parameter_names_only_a_status_a_stale_row_has(h, value: str) -> None:
    pending = pending_row(h)

    resp = delete(h, pending, value)

    assert resp.status_code == 422, resp.text
    assert connection(h, pending).status == "pending"


def test_a_conditional_delete_of_a_missing_row_is_404(h) -> None:
    resp = delete(h, str(uuid4()), "pending")

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "connection_not_found"
