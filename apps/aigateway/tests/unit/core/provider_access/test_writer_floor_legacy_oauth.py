"""G0 writer floor — the legacy OAuth flow claims at its callback the pair it observed at start.

# FEATURE: OME-1138 D18, G0 (contract §5.3, owner decision 2026-10-06) — OAuth begin records the
# pair it observed and never advances it; the callback's completion is an ownership change, so it
# claims that generation as the first write of its publication transaction.
# INVARIANT: a callback whose pair moved after its start loses with the legacy 409
# `profile_auth_conflict` and writes no document state, no blob and no shadow Connection.
# INVARIANT (D14 refinement): the shadow Connection of a legacy callback is written only while the
# pair still stands at the generation that callback published; a later ownership change wins.
"""

from __future__ import annotations

from typing import Any

import pytest
from connection_backed_admin_probes import (
    blob_at_connection_address,
    blob_at_profile_address,
    connections,
    document,
    marker,
    set_api_key,
)
from connection_backed_oauth_probes import (
    access_token_of,
    callback,
    pending_entry,
    start,
    use_tokens,
)
from provider_access_harness import PROVIDER, ProfileBackedHarness

from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.profile_models import ProfileState
from aigateway.core.provider_access import PairAuthority, PairAuthorityStore
from aigateway.core.provider_access.writer_floor import claim_pair
from aigateway.routes import auth as auth_routes


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


async def _claim_the_current_pair(account_id: str) -> None:
    await claim_pair(await PairAuthorityStore().read(account_id, PROVIDER))


def test_a_legacy_start_records_the_pair_it_observed_and_advances_nothing(
    legacy: ProfileBackedHarness,
) -> None:
    started = legacy.client.post(f"/v1/auth/{PROVIDER}/profiles", json={"name": "default"})

    assert started.status_code == 201
    entry = pending_entry(legacy, started.json()["state"])
    assert entry.observed_pair == PairAuthority(legacy.account_id, PROVIDER, "none", None, 0, None)
    # WHY unchanged: the migrated-only fence and the index generation keep their meaning.
    assert (entry.pair_generation, entry.oauth_generation) == (None, 1)
    assert marker(legacy).generation == 0


def test_a_fresh_legacy_callback_claims_the_pair_and_keeps_it_legacy_owned(
    legacy: ProfileBackedHarness,
) -> None:
    use_tokens(legacy, "fresh-tok")
    state = start(legacy).json()["state"]

    assert callback(legacy, state).status_code == 200

    pair = marker(legacy)
    assert (pair.migration_state, pair.generation) == ("none", 1)
    assert (pair.effective_connection_id, pair.migration_note) == (None, None)
    assert access_token_of(blob_at_profile_address(legacy)) == "fresh-tok"
    rows = connections(legacy)
    assert [row.status for row in rows] == ["active"]
    assert access_token_of(blob_at_connection_address(legacy, str(rows[0].id))) == "fresh-tok"


def test_a_legacy_callback_after_another_ownership_change_loses_and_writes_nothing(
    legacy: ProfileBackedHarness,
) -> None:
    use_tokens(legacy, "late-tok")
    state = start(legacy, name="default").json()["state"]
    # WHY another Profile name: the same name would already lose on the index CAS; the pair fence
    # is what makes a key set elsewhere on the pair supersede this flow.
    set_api_key(legacy, "work")

    response = callback(legacy, state)

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "profile_auth_conflict",
        "provider": PROVIDER,
        "profile": "default",
    }
    doc = document(legacy, "default")
    assert doc is not None and doc.state is ProfileState.PENDING
    assert blob_at_profile_address(legacy, "default") is None
    assert connections(legacy) == []
    assert marker(legacy).generation == 1


def test_a_quarantined_pairs_callback_keeps_its_state_and_note(
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
    use_tokens(legacy, "held-tok")
    state = start(legacy).json()["state"]

    assert callback(legacy, state).status_code == 200

    pair = marker(legacy)
    assert (pair.migration_state, pair.generation, pair.migration_note) == (
        "quarantined",
        2,
        "conflict",
    )


def test_no_shadow_is_written_when_the_pair_moved_before_the_shadow_row_exists(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_extract = auth_routes._extract_connection_identity

    async def extract_after_an_owner_change(app: Any, pending: Any, *args: Any) -> Any:
        await _claim_the_current_pair(pending.account_id)
        return await real_extract(app, pending, *args)

    monkeypatch.setattr(auth_routes, "_extract_connection_identity", extract_after_an_owner_change)
    use_tokens(legacy, "published-tok")
    state = start(legacy).json()["state"]

    assert callback(legacy, state).status_code == 200

    # WHY 200: the Profile publication committed while this flow still owned the pair; only the
    # shadow — a second record of a credential already superseded — is withheld.
    doc = document(legacy)
    assert doc is not None and doc.state is ProfileState.AUTHENTICATED
    assert access_token_of(blob_at_profile_address(legacy)) == "published-tok"
    assert connections(legacy) == []
    assert marker(legacy).generation == 2


def test_a_shadow_row_opened_before_the_pair_moved_is_revoked_without_a_blob(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_create = OAuthConnectionStore.create_pending

    async def create_then_lose_the_pair(self: Any, **kwargs: Any) -> Any:
        row = await real_create(self, **kwargs)
        await _claim_the_current_pair(str(kwargs["account_id"]))
        return row

    monkeypatch.setattr(OAuthConnectionStore, "create_pending", create_then_lose_the_pair)
    use_tokens(legacy, "published-tok")
    state = start(legacy).json()["state"]

    assert callback(legacy, state).status_code == 200

    assert connections(legacy) == []
    revoked = legacy.call(
        OAuthConnectionStore().list, legacy.account_id, provider=PROVIDER, status="revoked"
    )
    assert len(revoked) == 1
    assert blob_at_connection_address(legacy, str(revoked[0].id)) is None
    assert access_token_of(blob_at_profile_address(legacy)) == "published-tok"
