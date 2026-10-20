"""G0 refresh guard on a legacy pair — the owner presence fence (OME-1497).

# FEATURE: OME-1138 D18, G0 part 2 (contract §5.3) — a refresh publishes only while the document
# it read still owns the credential, even when nothing moved the marker.
# AIDEV-NOTE: helpers are bound from `test_writer_floor_refresh`; the intrusion runs inside the
# refresh's provider window on the app loop.
# WHY no re-auth in flight here: the Profile refresh route answers 410 since OME-1209 Stage E3, and
# the legacy re-auth start retired with its callback at Stage E3b. `stamp_refreshed` keeping a
# PENDING document PENDING is pinned in `test_profile_index.py`, and a native re-auth surviving a
# refresh in `test_writer_floor_refresh.py`.
"""

from __future__ import annotations

from typing import Any

import pytest
from connection_backed_admin_probes import blob_at_profile_address, marker
from connection_backed_oauth_probes import access_token_of
from provider_access_harness import PROVIDER, ProfileBackedHarness
from test_writer_floor_refresh import (
    Intrusion,
    expired_blob,
    profile_service,
    resolve_and_authorize,
    use_intruding_tokens,
)

from aigateway.core.credential_names import profile_id_for
from aigateway.core.provider_access import WriteConflict


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def a_document_removal(h: Any) -> Intrusion:
    """A Profile document removed WITHOUT a pair claim — the owner fence alone must catch it."""

    async def intrude() -> None:
        await h.client.app.state.profile_index.remove(
            profile_id_for(h.account_id, PROVIDER, "default")
        )

    return intrude


def test_a_refresh_loses_to_a_document_removal_that_moves_no_marker(legacy) -> None:
    # WHY: every remover on the product paths also claims the pair, so the marker re-read catches
    # them first; this pins the owner presence check that stands behind it.
    h = legacy
    h.seed_profile()
    h.blobs.write(profile_service(h), "default", expired_blob())
    before = marker(h)
    use_intruding_tokens(h, "fresh-tok", a_document_removal(h))

    with pytest.raises(WriteConflict):
        resolve_and_authorize(h)

    assert marker(h) == before
    assert access_token_of(blob_at_profile_address(h)) == "stale"
