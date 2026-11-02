"""A migrated pair's delete (OME-1208, S2'b1).

# FEATURE: OME-1138 Stage B (D14) — a migrated pair's delete clears the marker's effective
# reference, revokes the Connection and deletes the ONE blob, in that order and one transaction;
# since OME-1209 E4b it leaves a compat document as it was. Since OME-1209 E3b both writes run
# through the D18 admin PUT and DELETE (`set_pair_api_key`, `delete_pair`); the Profile-era ops
# 7-9 retired with their routes.
# WHY no rollback test: the D5 R1 legacy Profile reader retired at OME-1209 Stage E4a (spec §9
# Q10); a reset `none` pair resolves its Connection instead — test_connection_only_resolve.py::
# test_a_none_pair_resolves_its_connection_even_beside_a_profile_document.
"""

from __future__ import annotations

import pytest
from connection_backed_admin_probes import (
    DEFAULT,
    blob_at_name_address,
    connection,
    delete,
    marker,
)
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER

from aigateway.core.credential_names import credential_name_for
from aigateway.core.provider_access import TargetMissing


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


# --- the delete of a migrated pair ---------------------------------------------------------


def test_delete_revokes_the_effective_connection_and_clears_the_reference(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_blob(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")

    delete(migrated)

    assert blob_at_name_address(migrated) is None
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
