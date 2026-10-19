"""The D18 delete and a Connection still addressing the Profile blob (OME-1497, G0 §5.3).

# FEATURE: OME-1138 D18 — `delete_pair` ends a legacy-owned pair: its Profile document and the
# blob at that Profile's address go. Since OME-1209 E3b retired the Profile-era admin ops, the
# claim and owner-change tests of this module moved to `test_pair_admin_mutations.py`,
# `test_writer_floor.py` and `integration/test_pair_admin_mutations_postgres.py`; the shared-address
# guard (`addressed_by_a_live_connection`) is pinned in `test_pair_admin_publication.py`.
# INVARIANT (§5.3 "owner checks address the actual service/account address"): only a LIVE
# Connection at the Profile address keeps the blob; a revoked one does not.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from connection_backed_admin_probes import blob_at_profile_address, delete, document
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness

from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for

OLD_KEY = "sk-ant-api03-previous-legacy-key-1357"


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


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


# --- the delete ------------------------------------------------------------------------------


def test_a_revoked_connection_at_the_profile_address_does_not_keep_the_blob(
    legacy: ProfileBackedHarness,
) -> None:
    legacy.seed_profile(name="default", auth_type="api_key", credential=OLD_KEY)
    _seed_connection_at_the_profile_address(legacy, revoked=True)

    delete(legacy)

    assert document(legacy) is None
    assert blob_at_profile_address(legacy) is None
