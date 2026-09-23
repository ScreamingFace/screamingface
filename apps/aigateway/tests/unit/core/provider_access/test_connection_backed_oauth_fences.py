"""Fences and failures of the migrated pair's OAuth flow (OME-1208, S2'b2).

# INVARIANT (card, Stage B): stale-callback rejection and delete-wins are re-expressed on the
# Connection side — the marker generation the flow claimed at start is the fence, and a
# superseded callback answers today's `409 profile_auth_conflict`, writing nothing.
# INVARIANT: a failed exchange never destroys a working credential, never promotes a broken
# row to active, and never leaks the provider's body.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

import pytest
from connection_backed_admin_probes import (
    DEFAULT,
    KEY,
    blob_at_connection_address,
    blob_at_profile_address,
    connection,
    connections,
    document,
    marker,
    set_api_key,
)
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import (
    SENTINEL,
    access_token_of,
    callback,
    detach_effective,
    pending_entry,
    server_errors_as_responses,
    start,
    status,
    use_failing_exchange,
    use_tokens,
)
from provider_access_harness import ANTHROPIC, PROVIDER
from tortoise.exceptions import IntegrityError

from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.profile_models import ProfileState
from aigateway.core.provider_access import PairAuthorityStore

STALE = {"code": "profile_auth_conflict", "provider": PROVIDER, "profile": "default"}


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _open_flow(h: ConnectionBackedHarness, token: str) -> tuple[str, str, int]:
    """Seed an active migrated pair and open a flow; returns (effective id, state, generation)."""
    h.seed_profile()
    effective = h.migrated["default"]
    use_tokens(h, token)
    started = start(h)
    assert started.status_code == 201
    return effective, started.json()["state"], marker(h).generation


# --- fences -------------------------------------------------------------------------------------


def test_a_callback_whose_generation_was_overtaken_publishes_nothing(migrated) -> None:
    h = migrated
    effective, state, claimed = _open_flow(h, "stale-tok")
    # a concurrent authority write advances the pair past what this flow claimed
    h.call(
        PairAuthorityStore().advance,
        h.account_id,
        PROVIDER,
        expected_generation=claimed,
        migration_state="migrated",
        effective_connection_id=UUID(effective),
    )

    stale = callback(h, state)

    assert (stale.status_code, stale.json()["detail"]) == (409, STALE)
    assert "stale-tok" not in stale.text
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    assert blob_at_connection_address(h, effective) is None
    row = connection(h, effective)
    assert (row.status, row.auth_type) == ("active", "oauth")
    assert marker(h).generation == claimed + 1  # only the concurrent write moved it
    doc = document(h)
    assert doc is not None and doc.last_refreshed_at is None
    assert pending_entry(h, state) is None  # the state was consumed, as today


def test_a_delete_between_start_and_callback_wins(migrated) -> None:
    h = migrated
    effective, state, _ = _open_flow(h, "late-tok")

    assert h.client.delete(f"/v1/auth/{PROVIDER}/profiles/default").status_code == 204
    late = callback(h, state)

    assert (late.status_code, late.json()["detail"]) == (409, STALE)
    assert connection(h, effective).status == "revoked"  # never resurrected
    assert connections(h) == []  # the listing hides revoked rows: no new row was opened either
    assert blob_at_profile_address(h) is None
    assert blob_at_connection_address(h, effective) is None
    assert document(h) is None
    gone = marker(h)
    assert (gone.migration_state, gone.effective_connection_id) == ("migrated", None)
    assert h.client.get(f"/v1/auth/{PROVIDER}/profiles/default").status_code == 404


def test_an_api_key_written_between_start_and_callback_wins(migrated) -> None:
    h = migrated
    effective, state, _ = _open_flow(h, "late-tok")

    set_api_key(h)
    late = callback(h, state)

    assert (late.status_code, late.json()["detail"]) == (409, STALE)
    row = connection(h, effective)
    assert (row.status, row.auth_type) == ("active", "api_key")
    blob = json.loads(blob_at_profile_address(h) or "{}")
    assert blob.get("api_key") == KEY and "access_token" not in blob
    doc = document(h)
    assert doc is not None and (doc.state, doc.auth_type) == (ProfileState.AUTHENTICATED, "api_key")


# --- failures -----------------------------------------------------------------------------------


def test_a_failed_exchange_on_a_fresh_flow_marks_the_pending_connection_error(migrated) -> None:
    h = migrated
    h.seed_authority()
    detach_effective(h, h.migrated["default"])
    use_failing_exchange(h)
    started = start(h)
    assert started.status_code == 201
    state = started.json()["state"]
    claimed = marker(h)
    new_id = str(claimed.effective_connection_id)

    with server_errors_as_responses(h.client):
        failed = callback(h, state)

    assert failed.status_code == 500
    assert SENTINEL not in failed.text
    row = connection(h, new_id)
    assert (row.status, row.label) == ("error", f"error:{new_id}")
    assert blob_at_profile_address(h) is None
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.ERROR
    assert status(h).json()["state"] == "error"
    moved = marker(h)
    assert (str(moved.effective_connection_id), moved.generation) == (
        new_id,
        claimed.generation + 1,
    )


def test_a_failed_exchange_during_in_place_reauth_keeps_the_working_credential(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    use_failing_exchange(h)
    started = start(h)
    assert started.status_code == 201
    claimed = marker(h).generation

    with server_errors_as_responses(h.client):
        failed = callback(h, started.json()["state"])

    assert failed.status_code == 500
    assert SENTINEL not in failed.text
    row = connection(h, effective)
    assert (row.status, row.label) == ("active", "default")
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.AUTHENTICATED
    assert marker(h).generation == claimed  # nothing changed authority-wise
    target = h.call(h.access.resolve, h.account_id, PROVIDER, DEFAULT, plugin=ANTHROPIC)
    authorization = h.call(h.access.authorize, target, plugin=ANTHROPIC, provider=PROVIDER)
    assert any("tok" in value for value in authorization.headers.values())


def test_a_failing_credential_store_at_completion_rolls_everything_back(migrated, caplog) -> None:
    h = migrated
    effective, state, claimed = _open_flow(h, "lost-tok")
    store = h.client.app.state.credential_store

    async def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    h.monkeypatch.setattr(store, "write", boom)
    with caplog.at_level(logging.ERROR):
        failed = callback(h, state)

    assert failed.status_code == 503
    assert failed.json()["detail"]["code"] == "credential_store_unavailable"
    assert "lost-tok" not in failed.text and "lost-tok" not in caplog.text
    row = connection(h, effective)
    assert (row.status, row.auth_type) == ("active", "oauth")
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    doc = document(h)
    assert doc is not None and doc.last_refreshed_at is None  # the mirror rolled back too
    assert marker(h).generation == claimed  # the marker advance rolled back with it


def test_a_connection_revoked_between_read_and_publish_wins(migrated) -> None:
    h = migrated
    effective, state, claimed = _open_flow(h, "late-tok")
    index = h.client.app.state.profile_index
    real_get = index.get

    async def revoking_get(*args, **kwargs):
        result = await real_get(*args, **kwargs)
        store = OAuthConnectionStore()
        row = await store.get(h.account_id, effective)
        if row is not None and row.status != "revoked":
            await store.mark_revoked(row)  # a Connection-native delete lands mid-flight
        return result

    h.monkeypatch.setattr(index, "get", revoking_get)
    late = callback(h, state)

    assert (late.status_code, late.json()["detail"]) == (409, STALE)
    assert connection(h, effective).status == "revoked"
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    assert marker(h).generation == claimed  # the advance rolled back with the row fence


def test_an_identity_already_held_by_another_row_refuses_the_publication(migrated) -> None:
    h = migrated
    effective, state, claimed = _open_flow(h, "dup-tok")

    async def duplicate(self, connection, *, label, identity):
        raise IntegrityError("UNIQUE constraint failed: oauth_connections.identity_sub")

    h.monkeypatch.setattr(OAuthConnectionStore, "complete_active", duplicate)
    refused = callback(h, state)

    assert (refused.status_code, refused.json()["detail"]) == (409, STALE)
    row = connection(h, effective)
    assert (row.status, row.auth_type) == ("active", "oauth")
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    assert marker(h).generation == claimed
    doc = document(h)
    assert doc is not None and doc.last_refreshed_at is None


def test_a_failure_whose_pending_row_was_taken_marks_nothing(migrated) -> None:
    h = migrated
    h.seed_authority()
    detach_effective(h, h.migrated["default"])
    use_failing_exchange(h)
    started = start(h)
    assert started.status_code == 201
    claimed = marker(h)
    new_id = str(claimed.effective_connection_id)

    async def taken(self, connection, message):
        return None  # the row left `pending` under a writer that owns it now

    h.monkeypatch.setattr(OAuthConnectionStore, "mark_pending_error", taken)
    with server_errors_as_responses(h.client):
        failed = callback(h, started.json()["state"])

    assert failed.status_code == 500
    assert connection(h, new_id).status == "pending"
    assert marker(h).generation == claimed.generation  # the advance rolled back
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.PENDING


def test_the_manual_code_exchange_publishes_the_same_way(migrated) -> None:
    h = migrated
    effective, state, claimed = _open_flow(h, "pasted-tok")

    pasted = h.client.post(f"/v1/auth/{PROVIDER}/exchange-code", json={"code": "c", "state": state})

    assert pasted.status_code == 200
    assert access_token_of(blob_at_profile_address(h)) == "pasted-tok"
    assert blob_at_connection_address(h, effective) is None
    assert [str(c.id) for c in connections(h)] == [effective]
    assert marker(h).generation == claimed + 1
