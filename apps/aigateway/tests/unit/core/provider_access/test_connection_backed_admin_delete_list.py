"""`ConnectionBackedCredentialAdmin` — op 9 `delete`, op 7 `list`, R1 rollback (OME-1208, S2'b1).

# FEATURE: OME-1138 Stage B (D14) — a migrated pair's delete clears the marker's effective
# reference, removes the compat document, revokes the Connection and deletes the ONE blob, in
# that order and one transaction; `list` renders the pair from its effective Connection.
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
    list_summaries,
    marker,
    seed_legacy_provider,
    set_api_key,
)
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness

from aigateway.core.profile_models import ProfileState, credential_name_for
from aigateway.core.provider_access import (
    PairAuthorityStore,
    ProfileBackedProviderAccess,
    TargetMissing,
)


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


# --- op 9: delete on a migrated pair --------------------------------------------------------


def test_delete_revokes_the_effective_connection_and_clears_the_reference(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_document(name="default", auth_type="oauth")
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")

    delete(migrated, "default")

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


def test_delete_without_an_effective_connection_removes_the_compat_document_and_its_blob(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_document(name="default", auth_type="oauth")
    migrated.call(
        PairAuthorityStore().advance,
        migrated.account_id,
        PROVIDER,
        expected_generation=0,
        migration_state="migrated",
    )

    delete(migrated, "default")

    assert document(migrated) is None
    assert blob_at_profile_address(migrated) is None
    pair = marker(migrated)
    assert (pair.migration_state, pair.effective_connection_id, pair.generation) == (
        "migrated",
        None,
        2,
    )


def test_delete_refuses_a_missing_document_and_leaves_the_connection_alone(
    migrated: ConnectionBackedHarness,
) -> None:
    connection_id = migrated.seed_authority(name="default", auth_type="oauth")

    with pytest.raises(TargetMissing) as info:
        delete(migrated, "default")

    assert (info.value.provider, info.value.requested) == (PROVIDER, "default")
    assert connection(migrated, connection_id).status == "active"
    assert marker(migrated).generation == 1


# --- op 7: list over a migrated pair --------------------------------------------------------


def test_list_renders_migrated_documents_from_the_connection_and_omits_a_pair_without_one(
    migrated: ConnectionBackedHarness,
) -> None:
    document_state_says_authenticated = ProfileState.AUTHENTICATED
    migrated.seed_document(name="default", state=document_state_says_authenticated)
    migrated.seed_authority(name="default", state=ProfileState.ERROR, auth_type="oauth")
    codex = seed_legacy_provider(migrated, "codex")

    anthropic_rows = list_summaries(migrated, PROVIDER)
    everything = list_summaries(migrated)
    codex_rows = list_summaries(migrated, "codex")

    assert [(s.selector, s.auth_type, s.state) for s in anthropic_rows] == [
        ("default", "oauth", "error")
    ]
    doc = document(migrated)
    assert doc is not None
    errored = doc.model_copy(update={"state": ProfileState.ERROR})
    assert anthropic_rows[0].legacy_projection == errored.model_dump(mode="json")
    assert {(s.provider, s.state) for s in everything} == {
        (PROVIDER, "error"),
        ("codex", "authenticated"),
    }
    assert [s.legacy_projection for s in codex_rows] == [codex.model_dump(mode="json")]

    delete(migrated, "default")
    migrated.seed_document(name="default")  # a compat document with no effective Connection

    assert list_summaries(migrated, PROVIDER) == ()
    assert {s.provider for s in list_summaries(migrated)} == {"codex"}


# --- rollback availability (D5 R1) ----------------------------------------------------------


def test_the_legacy_document_and_blob_serve_the_new_key_after_a_marker_reset(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_document(name="default", auth_type="oauth")
    migrated.seed_authority(name="default", auth_type="oauth")
    set_api_key(migrated, "default")

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
