"""G0 writer floor — the legacy admin key set and delete claim the pair they observed (OME-1497).

# FEATURE: OME-1138 D18, G0 (contract §5.3) — the legacy Profile-backed body of op 8/op 9 runs for
# `none` and `quarantined` pairs; before the G1 bridge can adopt such a pair, a legacy writer that
# read the pair before another ownership change must lose instead of overwriting it.
# INVARIANT: the claim is the first write of the legacy transaction; a lost claim is the existing
# superseded `profile` conflict (409 `profile_conflict` at the edge) and writes no document, blob
# or marker.
# INVARIANT: a claim keeps the legacy authority — state, null reference and note — one generation
# on.
# INVARIANT (§5.3 "owner checks address the actual service/account address"): a legacy delete never
# removes a blob a live Connection still addresses — the shape an R1 rollback leaves.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from connection_backed_admin_probes import (
    KEY,
    admin_of,
    blob_at_profile_address,
    connection,
    delete,
    document,
    marker,
    set_api_key,
)
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness

from aigateway.core.auth.middleware import ANONYMOUS_ACCOUNT_ID
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.provider_access import PairAuthorityStore, WriteConflict
from aigateway.core.provider_access.writer_floor import claim_pair

OLD_KEY = "sk-ant-api03-previous-legacy-key-1357"


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _owner_change_after_the_branch_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Commit one concurrent ownership change right after the admin's pair read returns.

    # WHY at the read: the branch read is the capture point (§5.3, owner decision 2026-10-06);
    # a writer that changed the pair after it is exactly the one the floor must not overwrite.
    """
    real_read = PairAuthorityStore.read
    fired: list[str] = []

    async def read_then_lose_the_pair(self: Any, account_id: str, provider: str) -> Any:
        observed = await real_read(self, account_id, provider)
        if not fired:
            fired.append(provider)
            await claim_pair(observed)
        return observed

    monkeypatch.setattr(PairAuthorityStore, "read", read_then_lose_the_pair)


def _seed_marker(harness: ProfileBackedHarness, state: str, note: str | None) -> None:
    harness.call(
        PairAuthorityStore().advance,
        harness.account_id,
        PROVIDER,
        expected_generation=0,
        migration_state=state,
        migration_note=note,
    )


def _seed_connection_at_the_profile_address(
    harness: ProfileBackedHarness, *, revoked: bool = False
) -> str:
    """A Connection addressing the `default` Profile blob — what an R1 rollback leaves behind."""

    async def create() -> Any:
        store = OAuthConnectionStore()
        credential_provider = credential_service_provider_for(ANTHROPIC, PROVIDER)
        row = await store.create_api_key(
            account_id=harness.account_id,
            provider=PROVIDER,
            label="work",
            connection_id=uuid4(),
            credential_provider=credential_provider,
            credential_locator=credential_locator_for(
                credential_provider, harness.account_id, "default"
            ),
        )
        if revoked:
            await store.mark_revoked(row, "deleted")
        return row

    return str(harness.call(create).id)


def _api_key_at_profile_address(harness: ProfileBackedHarness) -> str | None:
    blob = blob_at_profile_address(harness)
    return None if blob is None else json.loads(blob)["api_key"]


# --- op 8 -----------------------------------------------------------------------------------


def test_a_key_set_claims_an_unmarked_pair_and_keeps_it_legacy_owned(
    legacy: ProfileBackedHarness,
) -> None:
    set_api_key(legacy, "default")

    pair = marker(legacy)
    assert (pair.migration_state, pair.generation) == ("none", 1)
    assert (pair.effective_connection_id, pair.migration_note) == (None, None)
    assert _api_key_at_profile_address(legacy) == KEY


def test_a_key_set_that_read_the_pair_before_another_owner_change_loses_and_writes_nothing(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy.seed_profile(name="default", auth_type="api_key", credential=OLD_KEY)
    before = document(legacy)
    _owner_change_after_the_branch_read(monkeypatch)

    with pytest.raises(WriteConflict) as info:
        set_api_key(legacy, "default")

    assert (info.value.kind, info.value.subject) == ("superseded", "profile")
    assert (info.value.provider, info.value.requested) == (PROVIDER, "default")
    assert document(legacy) == before
    assert _api_key_at_profile_address(legacy) == OLD_KEY
    # WHY generation 1: only the concurrent writer's claim committed.
    assert (marker(legacy).migration_state, marker(legacy).generation) == ("none", 1)


def test_a_first_key_set_that_lost_the_first_marker_creates_no_profile(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owner_change_after_the_branch_read(monkeypatch)

    with pytest.raises(WriteConflict):
        set_api_key(legacy, "default")

    assert document(legacy) is None
    assert blob_at_profile_address(legacy) is None


@pytest.mark.parametrize(("state", "note"), [("quarantined", "conflict"), ("none", "rollback")])
def test_a_key_set_and_a_delete_keep_the_state_and_the_note_of_a_legacy_owned_pair(
    legacy: ProfileBackedHarness, state: str, note: str
) -> None:
    _seed_marker(legacy, state, note)

    set_api_key(legacy, "default")
    after_set = marker(legacy)
    delete(legacy, "default")
    after_delete = marker(legacy)

    assert (after_set.migration_state, after_set.generation, after_set.migration_note) == (
        state,
        2,
        note,
    )
    assert (after_delete.migration_state, after_delete.generation) == (state, 3)
    assert (after_delete.effective_connection_id, after_delete.migration_note) == (None, note)


def test_the_anonymous_account_sets_a_key_on_its_first_marker(
    legacy: ProfileBackedHarness,
) -> None:
    # WHY: in `auth_mode=disabled` the anonymous account row may not exist yet; the marker's
    # foreign key names it, and a missing row must not read as a false superseded conflict.
    anonymous = str(ANONYMOUS_ACCOUNT_ID)

    summary = legacy.call(
        admin_of(legacy).set_api_key,
        anonymous,
        PROVIDER,
        raw_api_key=KEY,
        legacy_name="default",
    )

    assert (summary.auth_type, summary.state) == ("api_key", "authenticated")
    pair = legacy.call(PairAuthorityStore().read, anonymous, PROVIDER)
    assert (pair.migration_state, pair.generation) == ("none", 1)


# --- op 9 -----------------------------------------------------------------------------------


def test_a_delete_claims_the_pair_and_removes_the_profile_and_its_blob(
    legacy: ProfileBackedHarness,
) -> None:
    legacy.seed_profile(name="default", auth_type="api_key", credential=OLD_KEY)

    delete(legacy, "default")

    assert (marker(legacy).migration_state, marker(legacy).generation) == ("none", 1)
    assert document(legacy) is None
    assert blob_at_profile_address(legacy) is None


def test_a_delete_that_read_the_pair_before_another_owner_change_loses_and_keeps_the_profile(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy.seed_profile(name="default", auth_type="api_key", credential=OLD_KEY)
    before = document(legacy)
    _owner_change_after_the_branch_read(monkeypatch)

    with pytest.raises(WriteConflict) as info:
        delete(legacy, "default")

    assert (info.value.kind, info.value.subject) == ("superseded", "profile")
    assert document(legacy) == before
    assert _api_key_at_profile_address(legacy) == OLD_KEY
    assert marker(legacy).generation == 1


def test_a_legacy_delete_keeps_a_blob_a_live_connection_still_addresses(
    legacy: ProfileBackedHarness,
) -> None:
    _seed_marker(legacy, "none", "rollback")
    legacy.seed_profile(name="default", auth_type="api_key", credential=OLD_KEY)
    live = _seed_connection_at_the_profile_address(legacy)

    delete(legacy, "default")

    assert document(legacy) is None
    assert _api_key_at_profile_address(legacy) == OLD_KEY
    assert connection(legacy, live).status == "active"


def test_a_revoked_connection_at_the_profile_address_does_not_keep_the_blob(
    legacy: ProfileBackedHarness,
) -> None:
    legacy.seed_profile(name="default", auth_type="api_key", credential=OLD_KEY)
    _seed_connection_at_the_profile_address(legacy, revoked=True)

    delete(legacy, "default")

    assert document(legacy) is None
    assert blob_at_profile_address(legacy) is None
