"""A migrated pair's delete and the R1 rollback of its key write (OME-1208, S2'b1).

# FEATURE: OME-1138 Stage B (D14) — a migrated pair's delete clears the marker's effective
# reference, removes the compat document, revokes the Connection and deletes the ONE blob, in
# that order and one transaction. Since OME-1209 E3b both writes run through the D18 admin PUT
# and DELETE (`set_pair_api_key`, `delete_pair`); the Profile-era ops 7-9 retired with their
# routes.
# INVARIANT (D5 R1): resetting the marker with every blob kept hands the pair back to the legacy
# Profile path, which then serves the key the Connection-backed authority stored.
"""

from __future__ import annotations

import pytest
from connection_backed_admin_probes import (
    DEFAULT,
    KEY,
    blob_at_profile_address,
    connection,
    delete,
    document,
    marker,
    put_pair_key,
)
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER

from aigateway.core.credential_names import credential_name_for
from aigateway.core.provider_access import (
    PairAuthorityStore,
    ProfileBackedProviderAccess,
    TargetMissing,
)


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


# --- the delete of a migrated pair ---------------------------------------------------------


def test_delete_revokes_the_effective_connection_and_clears_the_reference(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_document(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")

    delete(migrated)

    assert document(migrated) is None
    assert blob_at_profile_address(migrated) is None
    assert connection(migrated, connection_id).status == "revoked"
    pair = marker(migrated)
    assert (pair.migration_state, pair.effective_connection_id, pair.generation) == (
        "migrated",
        None,
        2,
    )
    credential_name = credential_name_for(migrated.account_id, "default")
    assert migrated.evicted() == [credential_name]
    assert migrated.invalidated() == [credential_name]
    # Delete wins for good: the read side finds nothing to serve — no credential reappears.
    with pytest.raises(TargetMissing):
        migrated.call(
            migrated.access.resolve, migrated.account_id, PROVIDER, DEFAULT, plugin=ANTHROPIC
        )


# --- rollback availability (D5 R1) ----------------------------------------------------------


def test_the_legacy_document_and_blob_serve_the_new_key_after_a_marker_reset(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_document(name="default", auth_type="oauth")
    migrated.seed_authority(name="default", auth_type="oauth")
    put_pair_key(migrated)

    # R1: reset the marker, keep every blob — the legacy Profile path must serve the new key.
    migrated.call(
        PairAuthorityStore().advance,
        migrated.account_id,
        PROVIDER,
        expected_generation=marker(migrated).generation,
        migration_state="none",
    )
    legacy_access = ProfileBackedProviderAccess(migrated.client.app)
    target = migrated.call(
        legacy_access.resolve, migrated.account_id, PROVIDER, DEFAULT, plugin=ANTHROPIC
    )
    authorization = migrated.call(
        legacy_access.authorize, target, plugin=ANTHROPIC, provider=PROVIDER
    )

    assert (target.kind, target.auth_type) == ("stored", "api_key")
    assert target.credential_name == credential_name_for(migrated.account_id, "default")
    assert any(KEY in value for value in authorization.headers.values())
    assert marker(migrated).migration_state == "none"
