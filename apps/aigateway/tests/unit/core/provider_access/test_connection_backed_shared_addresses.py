"""Several addressers of ONE credential blob — the PR #1029 review findings (OME-1208, R1).

# FEATURE: Stage B Target — a Profile blob may be addressed by more than one row (a superseded
# `error` row beside the fresh row a re-auth opened). The rows come and go; the blob belongs to
# the pair.
# INVARIANT (D14, D5): a blob is deleted only when its LAST live Connection addresser goes; a
# re-auth under a name RETIRES the errored row that holds it instead of colliding with it.
# WHY no document addresser (OME-1209 E4b): a document neither keeps a blob alive nor receives a
# mirrored key any more.
# WHY "sibling" rows are seeded directly: a sibling (a second non-revoked row whose locator equals
# the effective row's) is pre-fix data, because D-R1-1 now prevents it at the source.
# WHY finding 2 (re-auth under the name an errored row holds) has no test here: its tests opened
# the flow through `POST /v1/auth/{provider}/profiles`, retired at OME-1209 Stage E3 (410); the
# native repair twins in `test_native_oauth_replaces_unusable_effective.py` and
# `test_native_repair_boundaries.py` cover it.
# WHY finding 3 (an alias key write mirrored on every document) has no test here: the alias write
# retired with the Profile-era admin ops at OME-1209 Stage E3b, and the D18 sibling mirror at E4b.

Retired at OME-1138 Stage E, E5c:
`test_a_rollback_refuses_a_pair_whose_key_lives_at_another_documents_address` — the
`migrate_profiles --rollback` tool it drove is deleted; successor: the import guard in
test_profile_index_offline_only.py.
Retired at OME-1138 Stage E, E5c: `test_a_rollback_without_alias_documents_still_resets_the_marker`
— the `migrate_profiles --rollback` tool it drove is deleted; successor: the import guard in
test_profile_index_offline_only.py.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from connection_backed_admin_probes import (
    blob_at_name_address,
    connection,
    marker,
)
from connection_backed_harness import CREDENTIAL_PROVIDER, ConnectionBackedHarness
from connection_backed_oauth_probes import access_token_of
from provider_access_harness import PROVIDER

from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for


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


# --- finding 1: delete keeps a blob another live addresser serves --------------------------------


def test_deleting_an_errored_sibling_keeps_the_blob_the_effective_row_serves(migrated) -> None:
    h = migrated
    h.seed_credential()
    effective = h.migrated["default"]
    sibling = seed_errored_sibling(h)

    resp = native_delete(h, sibling)

    assert resp.status_code == 204, resp.text
    assert connection(h, sibling).status == "revoked"
    assert access_token_of(blob_at_name_address(h)) == "tok"
    assert (marker(h).generation, str(marker(h).effective_connection_id)) == (1, effective)
    served = token(h, effective)
    assert served.status_code == 200, served.text
    assert served.json()["access_token"] == "tok"

    # The effective row is now the LAST live addresser: its delete removes the blob, as before.
    assert native_delete(h, effective).status_code == 204
    assert blob_at_name_address(h) is None


# WHY no "rolled-back Connection keeps the legacy Profile's blob" test (OME-1209 E4b): a document
# no longer keeps a blob alive, and the R1 rollback retired at OME-1138 Stage E, E5c.
