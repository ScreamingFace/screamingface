"""`ConnectionBackedCredentialAdmin` — routing and op 8 `set_api_key` (OME-1208, Stage B S2'b1).

# FEATURE: OME-1138 Stage B (D14) — for a `migrated` pair the legacy Profile routes' credential
# writes land on the pair's effective Connection through ONE authority; `none`/`quarantined`
# pairs keep the Profile-backed body untouched.
# INVARIANT (D16 (a), D5): the legacy document is rewritten as a faithful mirror on every
# authority write, so an R1 rollback (marker reset, blobs kept) serves the same credential from
# the legacy path — `test_connection_backed_admin_delete_list.py` proves the rollback itself.
# INVARIANT (design card): marker → index → Connection row → blob, one transaction; the marker
# advance is the fence, so a stale writer changes nothing and surfaces `WriteConflict`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from connection_backed_admin_probes import (
    KEY,
    MASKED,
    admin_of,
    blob_at_connection_address,
    blob_at_profile_address,
    connection,
    connections,
    delete,
    document,
    marker,
    set_api_key,
)
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness

from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.profile_models import ProfileDefaults, ProfileState, credential_name_for
from aigateway.core.provider_access import (
    ConnectionBackedCredentialAdmin,
    CredentialStoreUnavailable,
    PairAuthorityStore,
    ProfileBackedCredentialAdmin,
    ProviderCredentialAdmin,
    Selector,
    WriteConflict,
    provider_credential_admin_for,
)


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


# --- wiring + routing -----------------------------------------------------------------------


def test_the_app_wires_the_connection_backed_admin_over_the_profile_backed_one(
    migrated: ConnectionBackedHarness,
) -> None:
    admin = admin_of(migrated)
    assert isinstance(admin, ConnectionBackedCredentialAdmin)
    assert isinstance(admin, ProfileBackedCredentialAdmin)
    assert isinstance(admin, ProviderCredentialAdmin)
    assert provider_credential_admin_for(migrated.client.app) is admin


def test_an_unmarked_pair_is_served_by_the_profile_backed_body_after_one_marker_read(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[str] = []
    real_read = PairAuthorityStore.read
    real_set = ProfileBackedCredentialAdmin.set_api_key
    bodies: list[str] = []

    async def counting_read(self: Any, account_id: str, provider: str) -> Any:
        reads.append(provider)
        return await real_read(self, account_id, provider)

    async def legacy_body(self: Any, *args: Any, **kwargs: Any) -> Any:
        bodies.append("profile-backed")
        return await real_set(self, *args, **kwargs)

    monkeypatch.setattr(PairAuthorityStore, "read", counting_read)
    monkeypatch.setattr(ProfileBackedCredentialAdmin, "set_api_key", legacy_body)

    summary = set_api_key(legacy, "default")

    assert reads == [PROVIDER]
    assert bodies == ["profile-backed"]
    assert (summary.auth_type, summary.state) == ("api_key", "authenticated")
    assert json.loads(blob_at_profile_address(legacy) or "{}")["api_key"] == KEY
    assert connections(legacy) == []
    assert (marker(legacy).migration_state, marker(legacy).generation) == ("none", 0)


def test_a_quarantined_pair_keeps_the_legacy_body_and_its_marker(
    legacy: ProfileBackedHarness,
) -> None:
    legacy.call(
        PairAuthorityStore().advance,
        legacy.account_id,
        PROVIDER,
        expected_generation=0,
        migration_state="quarantined",
        migration_note="conflict",
    )

    set_api_key(legacy, "default")
    delete(legacy, "default")

    pair = marker(legacy)
    assert (pair.migration_state, pair.generation, pair.migration_note) == (
        "quarantined",
        1,
        "conflict",
    )
    assert connections(legacy) == []
    assert document(legacy) is None
    assert blob_at_profile_address(legacy) is None


def test_an_unreadable_marker_store_propagates_instead_of_guessing_the_owner(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(self: Any, account_id: str, provider: str) -> Any:
        raise RuntimeError("marker table unavailable")

    monkeypatch.setattr(PairAuthorityStore, "read", broken)

    with pytest.raises(RuntimeError):
        set_api_key(migrated, "default")

    assert document(migrated) is None
    assert blob_at_profile_address(migrated) is None


# --- op 8: set_api_key on a migrated pair ---------------------------------------------------


def test_set_api_key_writes_the_effective_connection_and_mirrors_the_document(
    migrated: ConnectionBackedHarness,
) -> None:
    # The document carries HISTORICAL defaults; op 8 takes none and must keep them (D2).
    migrated.seed_document(
        name="default", auth_type="oauth", defaults=ProfileDefaults(max_tokens=7)
    )
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")

    summary = set_api_key(migrated, "default")

    # The ONE blob of the pair sits at the Connection's locator (the Profile address); nothing
    # is written at the UUID-derived address a Connection-native write would use.
    assert json.loads(blob_at_profile_address(migrated) or "{}") == {
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
    doc = document(migrated)
    assert doc is not None
    assert (doc.state, doc.auth_type, doc.account_label, doc.scopes) == (
        ProfileState.AUTHENTICATED,
        "api_key",
        MASKED,
        [],
    )
    assert doc.defaults == ProfileDefaults(max_tokens=7)
    assert doc.last_refreshed_at is not None
    credential_name = credential_name_for(migrated.account_id, "default")
    assert migrated.evicted() == [credential_name]
    assert migrated.invalidated() == [credential_name]
    assert (summary.provider, summary.selector, summary.auth_type, summary.state) == (
        PROVIDER,
        "default",
        "api_key",
        "authenticated",
    )
    assert summary.legacy_projection == doc.model_dump(mode="json")


def test_set_api_key_reactivates_an_errored_connection_and_drops_the_error_placeholder(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_document(name="default", state=ProfileState.ERROR, auth_type="oauth")
    connection_id = migrated.seed_authority(
        name="default", state=ProfileState.ERROR, auth_type="oauth"
    )
    assert connection(migrated, connection_id).label == f"error:{connection_id}"

    set_api_key(migrated, "default")

    row = connection(migrated, connection_id)
    assert (row.status, row.auth_type, row.error_message) == (
        "active",
        "api_key",
        None,
    )
    # WHY: `mark_error` left the OAuth placeholder label; an API key has no identity to name the
    # row by, so it takes the Connection-native `api-key-<id>` label (unique by construction).
    assert row.label == f"api-key-{connection_id}"
    doc = document(migrated)
    assert doc is not None
    assert (doc.state, doc.auth_type) == (ProfileState.AUTHENTICATED, "api_key")
    assert migrated.profile_state("default") == "authenticated"


def test_set_api_key_completes_a_pending_connection(migrated: ConnectionBackedHarness) -> None:
    migrated.seed_document(name="default", state=ProfileState.PENDING, credential=None)
    connection_id = migrated.seed_authority(name="default", state=ProfileState.PENDING)

    set_api_key(migrated, "default")

    row = connection(migrated, connection_id)
    assert (row.status, row.auth_type, row.label) == (
        "active",
        "api_key",
        "default",
    )
    assert json.loads(blob_at_profile_address(migrated) or "{}")["api_key"] == KEY
    assert migrated.profile_state("default") == "authenticated"


@pytest.mark.parametrize("how", ["deleted", "revoked"])
def test_set_api_key_without_a_usable_effective_connection_starts_a_new_one(
    migrated: ConnectionBackedHarness, how: str
) -> None:
    migrated.seed_document(name="default", auth_type="oauth")
    old_id = migrated.seed_authority(name="default", auth_type="oauth")
    if how == "deleted":
        delete(migrated, "default")
    else:
        migrated.call(OAuthConnectionStore().mark_revoked, connection(migrated, old_id))
    generation_before = marker(migrated).generation

    set_api_key(migrated, "default")

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
    # INVARIANT (D5): the new Connection addresses the Profile blob, so a rollback still finds it.
    assert fresh.credential_locator == credential_locator_for(
        PROVIDER, migrated.account_id, "default"
    )
    assert json.loads(blob_at_profile_address(migrated) or "{}")["api_key"] == KEY
    assert blob_at_connection_address(migrated, new_id) is None
    assert connection(migrated, old_id).status == "revoked"
    doc = document(migrated)
    assert doc is not None
    assert (doc.state, doc.auth_type) == (ProfileState.AUTHENTICATED, "api_key")


def test_an_alias_name_writes_the_pairs_single_credential(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_document(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")

    set_api_key(migrated, "work")

    # One credential per pair: "work" is a second NAME for the same effective Connection.
    assert json.loads(blob_at_profile_address(migrated, "default") or "{}")["api_key"] == KEY
    assert blob_at_profile_address(migrated, "work") is None
    pair = marker(migrated)
    assert str(pair.effective_connection_id) == connection_id
    work = document(migrated, "work")
    assert work is not None
    assert (work.state, work.auth_type) == (ProfileState.AUTHENTICATED, "api_key")
    target = migrated.call(
        migrated.access.resolve,
        migrated.account_id,
        PROVIDER,
        Selector.from_header("work"),
        plugin=ANTHROPIC,
    )
    assert target.credential_name == credential_name_for(migrated.account_id, "default")


def test_a_stale_marker_loses_and_writes_nothing(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrated.seed_document(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")
    real_read = PairAuthorityStore.read
    other_writer = PairAuthorityStore()

    async def observe_then_lose(self: Any, account_id: str, provider: str) -> Any:
        observed = await real_read(self, account_id, provider)
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
        set_api_key(migrated, "default")

    assert (info.value.kind, info.value.subject) == ("superseded", "connection")
    assert (info.value.provider, info.value.requested) == (PROVIDER, "default")
    row = connection(migrated, connection_id)
    assert (row.status, row.auth_type) == ("active", "oauth")
    assert json.loads(blob_at_profile_address(migrated) or "{}")["access_token"] == "tok"
    doc = document(migrated)
    assert doc is not None
    assert doc.auth_type == "oauth"
    assert marker(migrated).generation == 2
    assert migrated.evicted() == []


def test_a_connection_revoked_between_read_and_publish_wins(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrated.seed_document(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")
    store = OAuthConnectionStore()
    index = migrated.client.app.state.profile_index
    real_get = index.get

    async def observe_then_lose_the_row(*args: Any, **kwargs: Any) -> Any:
        observed = await real_get(*args, **kwargs)
        # A Connection-native delete commits AFTER we read the effective row as active and before
        # we publish: the row leaves `active`. The marker is untouched (that route is not
        # slot-aware yet), so ONLY the Connection-row fence can catch this.
        row = await store.get(migrated.account_id, connection_id)
        assert row is not None
        await store.mark_revoked(row)
        return observed

    monkeypatch.setattr(index, "get", observe_then_lose_the_row)

    with pytest.raises(WriteConflict) as info:
        set_api_key(migrated, "default")

    assert (info.value.kind, info.value.subject) == ("superseded", "connection")
    row = connection(migrated, connection_id)
    # INVARIANT: nothing resurrected — the revoked row keeps its status AND its auth type (the
    # unfenced `set_auth_type` rolled back with the transaction).
    assert (row.status, row.auth_type) == ("revoked", "oauth")
    assert json.loads(blob_at_profile_address(migrated) or "{}")["access_token"] == "tok"
    doc = document(migrated)
    assert doc is not None
    assert doc.auth_type == "oauth"
    assert marker(migrated).generation == 1
    assert migrated.evicted() == []


def test_a_failing_credential_store_rolls_back_the_connection_and_the_marker(
    migrated: ConnectionBackedHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    migrated.seed_document(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")

    async def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(f"store exploded while holding {KEY}")

    monkeypatch.setattr(migrated.client.app.state.credential_store, "write", boom)

    with pytest.raises(CredentialStoreUnavailable) as info:
        set_api_key(migrated, "default")

    assert KEY not in str(info.value) and KEY not in repr(info.value)
    assert KEY not in caplog.text
    # ONE transaction: the Connection row, the document and the marker all rolled back.
    row = connection(migrated, connection_id)
    assert (row.status, row.auth_type) == ("active", "oauth")
    doc = document(migrated)
    assert doc is not None
    assert (doc.state, doc.auth_type) == (ProfileState.AUTHENTICATED, "oauth")
    assert json.loads(blob_at_profile_address(migrated) or "{}")["access_token"] == "tok"
    assert marker(migrated).generation == 1
    assert migrated.evicted() == []
