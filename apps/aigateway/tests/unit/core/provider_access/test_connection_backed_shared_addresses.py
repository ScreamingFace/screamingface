"""Several addressers of ONE credential blob — the PR #1029 review findings (OME-1208, R1).

# FEATURE: Stage B Target — a Profile blob may be addressed by more than one row (a superseded
# `error` row beside the fresh row a re-auth opened; the backfill's row beside the legacy Profile
# after an R1 rollback) and by every compat document of a migrated pair. The rows come and go;
# the blob belongs to the pair.
# INVARIANT (D14, D5): a blob is deleted only when its LAST live addresser goes; a re-auth under a
# name RETIRES the errored row that holds it instead of colliding with it; a key written for a
# migrated pair is mirrored on every document of the pair, so the document at the key's address
# is coherent after a rollback.
# AIDEV-NOTE: "sibling" below means a second non-revoked row whose locator equals the effective
# row's — pre-fix data, seeded directly, because D-R1-1 now prevents it at the source.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from backfill_probes import run
from connection_backed_admin_probes import (
    DEFAULT,
    MASKED,
    blob_at_profile_address,
    connection,
    connections,
    document,
    marker,
    set_api_key,
)
from connection_backed_harness import CREDENTIAL_PROVIDER, ConnectionBackedHarness
from connection_backed_oauth_probes import access_token_of, callback, start, status, use_tokens
from provider_access_harness import ANTHROPIC, PROVIDER

from aigateway import migrate_profiles
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.profile_models import ProfileState, credential_name_for
from aigateway.core.provider_access import Selector
from aigateway.core.provider_access.pair_authority import PairAuthorityStore


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def native_delete(h: Any, connection_id: str) -> httpx.Response:
    return h.client.delete(f"/v1/oauth/connections/{connection_id}")


def token(h: Any, connection_id: str) -> httpx.Response:
    return h.client.get(f"/v1/oauth/connections/{connection_id}/token")


def seed_errored_sibling(h: Any, *, name: str = "default", label: str = "old") -> str:
    """A second, non-revoked `error` row at the SAME Profile address as the effective row."""

    async def seed() -> str:
        store = OAuthConnectionStore()
        row = await store.create_pending(
            account_id=h.account_id,
            provider=PROVIDER,
            label=label,
            connection_id=uuid4(),
            credential_provider=CREDENTIAL_PROVIDER,
            credential_locator=credential_locator_for(CREDENTIAL_PROVIDER, h.account_id, name),
        )
        row = await store.complete(row, label=label, identity=None)
        errored = await store.mark_error(row, "rejected")
        assert errored is not None
        return str(errored.id)

    return h.call(seed)


def rollback(h: Any) -> None:
    """R1: the marker reset `migrate_profiles --rollback` performs — every row and blob kept."""
    markers = PairAuthorityStore()
    current = h.call(markers.read, h.account_id, PROVIDER)
    h.call(
        markers.advance,
        h.account_id,
        PROVIDER,
        expected_generation=current.generation,
        migration_state="none",
        migration_note="rollback",
    )


# --- finding 2: re-auth under the name an errored row still holds --------------------------------


def test_a_migrated_api_key_pair_in_error_switches_to_oauth_under_its_name(migrated) -> None:
    h = migrated
    h.seed_profile(state=ProfileState.ERROR, auth_type="api_key")
    old = h.migrated["default"]
    assert connection(h, old).label == "default"  # an api_key row keeps its label in `error`
    use_tokens(h, "fresh-tok")

    started = start(h)

    assert started.status_code == 201, started.text
    new_id = str(marker(h).effective_connection_id)
    assert new_id != old
    row = connection(h, new_id)
    assert (row.status, row.auth_type, row.label) == ("pending", "oauth", "default")
    assert connection(h, old).status == "revoked"
    assert [str(c.id) for c in connections(h)] == [new_id]

    assert callback(h, started.json()["state"]).status_code == 200
    assert connection(h, new_id).status == "active"
    assert access_token_of(blob_at_profile_address(h)) == "fresh-tok"
    assert status(h).json()["state"] == "authenticated"


def test_a_fresh_flow_retires_the_errored_oauth_row_it_supersedes(migrated) -> None:
    h = migrated
    h.seed_profile(state=ProfileState.ERROR)
    old = h.migrated["default"]
    use_tokens(h, "fresh-tok")

    started = start(h)

    assert started.status_code == 201, started.text
    assert connection(h, old).status == "revoked"
    assert len(connections(h)) == 1
    assert access_token_of(blob_at_profile_address(h)) == "tok"  # the blob waits for the callback


# --- finding 1: delete keeps a blob another live addresser serves --------------------------------


def test_deleting_an_errored_sibling_keeps_the_blob_the_effective_row_serves(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    sibling = seed_errored_sibling(h)

    resp = native_delete(h, sibling)

    assert resp.status_code == 204, resp.text
    assert connection(h, sibling).status == "revoked"
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    assert (marker(h).generation, str(marker(h).effective_connection_id)) == (1, effective)
    served = token(h, effective)
    assert served.status_code == 200, served.text
    assert served.json()["access_token"] == "tok"

    # The effective row is now the LAST live addresser: its delete removes the blob, as before.
    assert native_delete(h, effective).status_code == 204
    assert blob_at_profile_address(h) is None


def test_deleting_a_rolled_back_connection_keeps_the_legacy_profiles_blob(migrated) -> None:
    h = migrated
    h.seed_profile()
    leftover = h.migrated["default"]
    rollback(h)
    assert marker(h).migration_state == "none"

    resp = native_delete(h, leftover)

    assert resp.status_code == 204, resp.text
    assert connection(h, leftover).status == "revoked"
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    assert document(h) is not None
    assert status(h).json()["state"] == "authenticated"
    target = h.call(h.access.resolve, h.account_id, PROVIDER, DEFAULT, plugin=ANTHROPIC)
    assert target.credential_name == credential_name_for(h.account_id, "default")


# --- finding 3: a key written for the pair is mirrored on every document of the pair -------------


def test_an_alias_key_write_mirrors_the_document_at_the_keys_address(migrated) -> None:
    h = migrated
    h.seed_document(name="default", auth_type="oauth")
    h.seed_authority(name="default", auth_type="oauth")

    set_api_key(h, "work")

    default = document(h, "default")
    assert default is not None
    assert (default.state, default.auth_type, default.account_label) == (
        ProfileState.AUTHENTICATED,
        "api_key",
        MASKED,
    )
    work = document(h, "work")
    assert work is not None and work.auth_type == "api_key"

    # After an R1 rollback the legacy path reads `default` from its document AND its blob: both
    # say api_key.
    rollback(h)
    body = status(h, "default").json()
    assert (body["state"], body["auth_type"]) == ("authenticated", "api_key")


# --- R1 rehearsal over an address a document does not own: refused and reported ---------------


def rollback_record(h: Any) -> Any:
    report = run(h, "rollback")
    (record,) = [r for a in report.accounts for r in a.records if r.provider == PROVIDER]
    return report, record


def test_a_rollback_refuses_a_pair_whose_key_lives_at_another_documents_address(migrated) -> None:
    h = migrated
    h.seed_document(name="default", auth_type="oauth")
    effective = h.seed_authority(name="default", auth_type="oauth")
    set_api_key(h, "work")
    generation = marker(h).generation

    report, record = rollback_record(h)

    # WHY refused: the legacy `work` document addresses a blob that does not exist — resetting the
    # marker would publish an authenticated Profile that serves nothing. Never guess, report.
    assert (record.category, record.applied, record.alias_documents) == (
        "rollback_refused_alias_documents",
        False,
        1,
    )
    assert migrate_profiles.exit_code_for(report) == migrate_profiles.EXIT_REFUSED
    pair = marker(h)
    assert (pair.migration_state, pair.generation) == ("migrated", generation)
    assert str(pair.effective_connection_id) == effective
    # Access through `work` keeps working — through the pair's one Connection, at its address.
    target = h.call(
        h.access.resolve, h.account_id, PROVIDER, Selector.from_header("work"), plugin=ANTHROPIC
    )
    assert target.credential_name == credential_name_for(h.account_id, "default")
    assert status(h, "work").json()["state"] == "authenticated"


def test_a_rollback_refuses_a_uuid_addressed_pair_that_gained_a_document(migrated) -> None:
    h = migrated
    row = h.seed_connection(label="default", credential="ctok")
    (applied,) = run(h, "apply").accounts[0].records
    assert (applied.category, applied.applied) == ("connection_only", True)
    set_api_key(h, "default")
    assert blob_at_profile_address(h, "default") is None  # the key went to the UUID address

    _report, record = rollback_record(h)

    assert (record.category, record.applied) == ("rollback_refused_alias_documents", False)
    assert (marker(h).migration_state, str(marker(h).effective_connection_id)) == ("migrated", row)


def test_a_rollback_without_alias_documents_still_resets_the_marker(migrated) -> None:
    h = migrated
    h.seed_profile()

    report, record = rollback_record(h)

    assert (record.category, record.applied, record.alias_documents) == ("rollback", True, 0)
    assert migrate_profiles.exit_code_for(report) == migrate_profiles.EXIT_OK
    assert marker(h).migration_state == "none"
