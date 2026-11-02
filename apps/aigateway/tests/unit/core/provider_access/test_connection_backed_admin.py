"""`ConnectionBackedCredentialAdmin` — the D18 key write on a migrated pair (OME-1208, S2'b1).

# FEATURE: OME-1138 Stage B (D14) — for a `migrated` pair a credential write lands on the pair's
# effective Connection through ONE authority. Since OME-1209 E3b these tests drive it through the
# D18 admin PUT (`set_pair_api_key`), its only caller; the Profile-era op 8 retired with its
# routes.
# WHY no mirror (OME-1209 E4b): the authority write leaves a legacy document as it was.
# INVARIANT (design card): marker → Connection row → blob, one transaction; the marker advance is
# the fence, so a stale writer changes nothing and surfaces `WriteConflict`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from connection_backed_admin_probes import (
    KEY,
    blob_at_connection_address,
    blob_at_name_address,
    connection,
    delete,
    marker,
    put_pair_key,
)
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import PROVIDER

from aigateway.core.credential_names import credential_name_for
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.provider_access import (
    CredentialStoreUnavailable,
    PairAuthorityStore,
    WriteConflict,
)
from tests.unit.seed_state import SeedState


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


# --- routing -------------------------------------------------------------------------------


def test_an_unreadable_marker_store_propagates_instead_of_guessing_the_owner(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(self: Any, account_id: str, provider: str) -> Any:
        raise RuntimeError("marker table unavailable")

    monkeypatch.setattr(PairAuthorityStore, "read", broken)

    with pytest.raises(RuntimeError):
        put_pair_key(migrated)

    assert blob_at_name_address(migrated) is None


# --- the D18 key write on a migrated pair ---------------------------------------------------


def test_set_api_key_writes_the_effective_connection_and_leaves_the_document(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_blob(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")

    put_pair_key(migrated)

    # The ONE blob of the pair sits at the Connection's locator (the Profile address); nothing
    # is written at the UUID-derived address a Connection-native write would use.
    assert json.loads(blob_at_name_address(migrated) or "{}") == {
        "auth_type": "api_key",
        "api_key": KEY,
    }
    assert blob_at_connection_address(migrated, connection_id) is None
    row = connection(migrated, connection_id)
    assert (row.status, row.auth_type, row.label) == (
        "active",
        "api_key",
        "default",
    )
    assert row.error_message is None
    pair = marker(migrated)
    assert (pair.migration_state, str(pair.effective_connection_id), pair.generation) == (
        "migrated",
        connection_id,
        2,
    )
    credential_name = credential_name_for(migrated.account_id, "default")
    assert migrated.evicted() == [credential_name]
    assert migrated.invalidated() == [credential_name]


def test_set_api_key_reactivates_an_errored_connection_and_drops_the_error_placeholder(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_blob(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(
        name="default", state=SeedState.ERROR, auth_type="oauth"
    )
    assert connection(migrated, connection_id).label == f"error:{connection_id}"

    put_pair_key(migrated)

    row = connection(migrated, connection_id)
    assert (row.status, row.auth_type, row.error_message) == (
        "active",
        "api_key",
        None,
    )
    # WHY: `mark_error` left the OAuth placeholder label; an API key has no identity to name the
    # row by, so it takes the Connection-native `api-key-<id>` label (unique by construction).
    assert row.label == f"api-key-{connection_id}"
    assert migrated.credential_state("default") == "authenticated"


def test_set_api_key_completes_a_pending_connection(migrated: ConnectionBackedHarness) -> None:
    connection_id = migrated.seed_authority(name="default", state=SeedState.PENDING)

    put_pair_key(migrated)

    row = connection(migrated, connection_id)
    assert (row.status, row.auth_type, row.label) == (
        "active",
        "api_key",
        "default",
    )
    assert json.loads(blob_at_name_address(migrated) or "{}")["api_key"] == KEY
    assert migrated.credential_state("default") == "authenticated"


# WHY "deleted" only: a revoked effective row with a stale reference is an inconsistent pair the
# PUT refuses (`test_pair_admin_mutations.py::test_an_inconsistent_pair_is_unavailable`).
@pytest.mark.parametrize("how", ["deleted"])
def test_set_api_key_without_a_usable_effective_connection_starts_a_new_one(
    migrated: ConnectionBackedHarness, how: str
) -> None:
    migrated.seed_blob(name="default", auth_type="oauth")
    old_id = migrated.seed_authority(name="default", auth_type="oauth")
    if how == "deleted":
        delete(migrated)
    generation_before = marker(migrated).generation

    put_pair_key(migrated)

    pair = marker(migrated)
    assert pair.migration_state == "migrated"
    assert pair.generation == generation_before + 1
    assert pair.effective_connection_id is not None
    new_id = str(pair.effective_connection_id)
    assert new_id != old_id
    fresh = connection(migrated, new_id)
    assert (fresh.status, fresh.auth_type, fresh.label) == (
        "active",
        "api_key",
        f"api-key-{new_id}",
    )
    # WHY its own address (E5a, history cleanup): a minted row never takes a Profile address.
    assert fresh.credential_locator == credential_locator_for(PROVIDER, migrated.account_id, new_id)
    assert json.loads(blob_at_connection_address(migrated, new_id) or "{}")["api_key"] == KEY
    assert blob_at_name_address(migrated) is None
    assert connection(migrated, old_id).status == "revoked"


def test_a_stale_marker_loses_and_writes_nothing(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrated.seed_blob(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")
    real_read = PairAuthorityStore.read
    other_writer = PairAuthorityStore()
    reads: list[int] = []

    async def observe_then_lose(self: Any, account_id: str, provider: str) -> Any:
        observed = await real_read(self, account_id, provider)
        reads.append(observed.generation)
        # WHY the second read: the PUT captures again after the key check and fences on that one.
        if len(reads) == 2:
            # Another worker advances the pair between our read and our publish — outside our
            # transaction, exactly as a concurrent commit would.
            await other_writer.advance(
                account_id,
                provider,
                expected_generation=observed.generation,
                migration_state="migrated",
                effective_connection_id=observed.effective_connection_id,
            )
        return observed

    monkeypatch.setattr(PairAuthorityStore, "read", observe_then_lose)

    with pytest.raises(WriteConflict) as info:
        put_pair_key(migrated)

    assert (info.value.kind, info.value.subject) == ("superseded", "connection")
    assert (info.value.provider, info.value.requested) == (PROVIDER, None)
    row = connection(migrated, connection_id)
    assert (row.status, row.auth_type) == ("active", "oauth")
    assert json.loads(blob_at_name_address(migrated) or "{}")["access_token"] == "tok"
    assert marker(migrated).generation == 2
    assert migrated.evicted() == []


def test_a_connection_revoked_between_read_and_publish_wins(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrated.seed_blob(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")
    store = OAuthConnectionStore()
    real_list = OAuthConnectionStore.list
    reads: list[int] = []

    async def observe_then_lose_the_row(self: Any, *args: Any, **kwargs: Any) -> Any:
        observed = await real_list(self, *args, **kwargs)
        reads.append(len(observed))
        # WHY the second read: the PUT captures again after the key check, outside its transaction,
        # and fences on that capture.
        if len(reads) == 2:
            # A Connection-native delete commits AFTER we read the effective row as active and
            # before we publish: the row leaves `active`. The marker is untouched (that route is
            # not slot-aware yet), so ONLY the Connection-row fence can catch this.
            row = await store.get(migrated.account_id, connection_id)
            assert row is not None
            await store.mark_revoked(row)
        return observed

    monkeypatch.setattr(OAuthConnectionStore, "list", observe_then_lose_the_row)

    with pytest.raises(WriteConflict) as info:
        put_pair_key(migrated)

    assert (info.value.kind, info.value.subject) == ("superseded", "connection")
    row = connection(migrated, connection_id)
    # INVARIANT: nothing resurrected — the revoked row keeps its status AND its auth type (the
    # unfenced `set_auth_type` rolled back with the transaction).
    assert (row.status, row.auth_type) == ("revoked", "oauth")
    assert json.loads(blob_at_name_address(migrated) or "{}")["access_token"] == "tok"
    assert marker(migrated).generation == 1
    assert migrated.evicted() == []


def test_a_failing_credential_store_rolls_back_the_connection_and_the_marker(
    migrated: ConnectionBackedHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    migrated.seed_blob(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")

    async def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(f"store exploded while holding {KEY}")

    monkeypatch.setattr(migrated.client.app.state.credential_store, "write", boom)

    with pytest.raises(CredentialStoreUnavailable) as info:
        put_pair_key(migrated)

    assert KEY not in str(info.value) and KEY not in repr(info.value)
    assert KEY not in caplog.text
    # ONE transaction: the Connection row and the marker both rolled back.
    row = connection(migrated, connection_id)
    assert (row.status, row.auth_type) == ("active", "oauth")
    assert json.loads(blob_at_name_address(migrated) or "{}")["access_token"] == "tok"
    assert marker(migrated).generation == 1
    assert migrated.evicted() == []
