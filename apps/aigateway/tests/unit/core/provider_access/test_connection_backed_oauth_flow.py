"""The Profile-facade OAuth flow of a MIGRATED pair publishes its effective Connection (S2'b2).

# FEATURE: Stage B Target, D14 — "OAuth callback publication included": for a `migrated` pair the
# callback republishes the pair's ONE effective Connection and the blob its locator names; no
# shadow Connection, no UUID-addressed blob, the Profile index only mirrored (D-S2b-2).
# INVARIANT: an unmigrated or quarantined pair keeps today's flow byte for byte — shadow row and
# UUID blob included — after exactly one marker read.
# WHY flows open through `start` (a storage seeder): OME-1209 Stage E3 retired
# `POST /v1/auth/{provider}/profiles` (410), but the callback branches it fed ship until E4. The
# start-time edges (defaults refused, a restart reusing its row, a marker moved under the start, a
# foreign row holding the label) tested the retired route itself and retired with it; the native
# start `POST /v1/oauth/connections` carries its own label and fence tests
# (`tests/unit/test_oauth_connections_routes.py` and
# `test_native_oauth_replaces_unusable_effective.py`).
"""

from __future__ import annotations

from uuid import UUID

import pytest
from connection_backed_admin_probes import (
    DEFAULT,
    blob_at_connection_address,
    blob_at_profile_address,
    connection,
    connections,
    document,
    marker,
)
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import (
    access_token_of,
    callback,
    detach_effective,
    pending_entry,
    start,
    use_tokens,
)
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness

from aigateway.core.credential_names import credential_name_for
from aigateway.core.oauth.store import credential_key_for, credential_locator_for
from aigateway.core.profile_models import ProfileState
from aigateway.core.provider_access import PairAuthorityStore, TargetPending


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


# --- migrated pairs ----------------------------------------------------------------------------


def test_the_callback_republishes_the_effective_connection_in_place(migrated) -> None:
    h = migrated
    h.seed_profile()  # document + Profile-addressed blob "tok" + active Connection + marker (gen 1)
    effective = h.migrated["default"]
    use_tokens(h, "new-tok")

    state = start(h)
    # D-S2b2-3: an ACTIVE row re-authenticates IN PLACE — the pair stays usable while the flow is
    # open, and the marker (not the document's generation) is what this flow claimed.
    assert connection(h, effective).status == "active"
    assert h.profile_state() == "authenticated"
    claimed = marker(h)
    assert (str(claimed.effective_connection_id), claimed.generation) == (effective, 2)
    entry = pending_entry(h, state)
    assert (entry.pair_generation, entry.connection_id, entry.oauth_generation) == (2, None, None)

    assert callback(h, state).status_code == 200

    row = connection(h, effective)
    assert (row.status, row.auth_type, row.label) == ("active", "oauth", "default")
    assert row.last_refreshed_at is not None
    assert access_token_of(blob_at_profile_address(h)) == "new-tok"
    # D-S2b2-4: no shadow row, no UUID-addressed blob — ONE row, ONE blob.
    assert blob_at_connection_address(h, effective) is None
    assert [str(c.id) for c in connections(h)] == [effective]
    after = marker(h)
    assert (after.migration_state, str(after.effective_connection_id), after.generation) == (
        "migrated",
        effective,
        3,
    )
    doc = document(h)
    assert doc is not None
    assert (doc.state, doc.auth_type) == (ProfileState.AUTHENTICATED, "oauth")
    assert doc.last_refreshed_at is not None
    assert h.profile_state() == "authenticated"
    name = credential_name_for(h.account_id, "default")
    assert name in h.evicted() and name in h.invalidated()
    assert pending_entry(h, state) is None


def test_a_pair_without_an_effective_connection_starts_a_pending_one(migrated) -> None:
    h = migrated
    h.seed_authority()
    old = h.migrated["default"]
    detach_effective(h, old)  # after a delete: marker migrated, effective None, no document
    assert document(h) is None
    use_tokens(h, "fresh-tok")

    state = start(h)
    claimed = marker(h)
    new_id = str(claimed.effective_connection_id)
    assert new_id != old
    row = connection(h, new_id)
    assert (row.status, row.auth_type, row.label) == ("pending", "oauth", "default")
    # the new row addresses the requested name's Profile blob — an R1 rollback reads it as today
    assert row.credential_locator == credential_locator_for(PROVIDER, h.account_id, "default")
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.PENDING
    assert h.connection_status(new_id) == "pending"
    with pytest.raises(TargetPending):
        h.call(h.access.resolve, h.account_id, PROVIDER, DEFAULT, plugin=ANTHROPIC)

    assert callback(h, state).status_code == 200

    row = connection(h, new_id)
    assert (row.status, row.label) == ("active", "default")
    assert access_token_of(blob_at_profile_address(h)) == "fresh-tok"
    assert blob_at_connection_address(h, new_id) is None
    assert connection(h, old).status == "revoked"  # never revived
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.AUTHENTICATED
    target = h.call(h.access.resolve, h.account_id, PROVIDER, DEFAULT, plugin=ANTHROPIC)
    assert target.credential_name == credential_name_for(h.account_id, "default")
    assert marker(h).generation == claimed.generation + 1


def test_a_connection_only_pair_reauthenticates_at_its_own_locator(migrated) -> None:
    h = migrated
    connection_id = h.seed_connection(label="default", credential="ctok")  # UUID locator
    current = marker(h)
    h.call(
        PairAuthorityStore().advance,
        h.account_id,
        PROVIDER,
        expected_generation=current.generation,
        migration_state="migrated",
        effective_connection_id=UUID(connection_id),
    )
    assert document(h) is None
    use_tokens(h, "re-tok")

    state = start(h)
    assert callback(h, state).status_code == 200

    # locator-authoritative: the blob moves where the row points, never to the Profile address
    assert access_token_of(blob_at_connection_address(h, connection_id)) == "re-tok"
    assert blob_at_profile_address(h) is None
    row = connection(h, connection_id)
    assert (row.status, row.auth_type, row.label) == ("active", "oauth", "default")
    doc = document(h)
    assert doc is not None and (doc.state, doc.auth_type) == (ProfileState.AUTHENTICATED, "oauth")
    assert credential_key_for(h.account_id, connection_id) in h.evicted()
    assert [str(c.id) for c in connections(h)] == [connection_id]


# --- unmigrated pairs: today's flow, byte for byte ---------------------------------------------


def test_an_unmigrated_pair_keeps_the_legacy_flow_and_stays_legacy_owned(legacy) -> None:
    h = legacy
    use_tokens(h, "legacy-tok")

    state = start(h, name="work")

    assert callback(h, state).status_code == 200

    # WHY 1 (OME-1497, G0 §5.3): the callback claims the pair its begin observed; still `none`.
    claimed = marker(h)
    assert (claimed.migration_state, claimed.generation) == ("none", 1)
    assert access_token_of(blob_at_profile_address(h, "work")) == "legacy-tok"
    doc = document(h, "work")
    assert doc is not None and doc.state is ProfileState.AUTHENTICATED
    # today's dual write stands for a pair the legacy Profile owns: the shadow row + UUID blob
    rows = connections(h)
    assert [(row.status, row.label) for row in rows] == [("active", "work")]
    assert access_token_of(blob_at_connection_address(h, str(rows[0].id))) == "legacy-tok"


def test_a_quarantined_pair_keeps_the_legacy_flow_and_its_marker(legacy) -> None:
    h = legacy
    h.call(
        PairAuthorityStore().advance,
        h.account_id,
        PROVIDER,
        expected_generation=0,
        migration_state="quarantined",
        migration_note="conflict",
    )
    use_tokens(h, "held-tok")

    state = start(h)
    assert callback(h, state).status_code == 200

    held = marker(h)
    # WHY 2 (OME-1497, G0 §5.3): the callback claims the pair, keeping its state and note.
    assert (held.migration_state, held.generation, held.migration_note) == (
        "quarantined",
        2,
        "conflict",
    )
    assert access_token_of(blob_at_profile_address(h)) == "held-tok"
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.AUTHENTICATED
