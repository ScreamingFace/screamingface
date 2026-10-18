"""G0 refresh guard on a legacy pair — re-auth in flight, and the owner presence fence (OME-1497).

# FEATURE: OME-1138 D18, G0 part 2 (contract §5.3) — "a refresh must not turn an in-flight re-auth
# callback into a false 409". A legacy re-auth start on an unmarked pair moves no marker; it only
# flips the document to PENDING, so the refresh's document stamp is what must leave it alone.
# AIDEV-NOTE: helpers are bound from `test_writer_floor_refresh`; the intrusion runs inside the
# refresh's provider window on the app loop.
# WHY one refresh path: the Profile refresh route answers 410 since OME-1209 Stage E3, so its
# twin of the in-flight re-auth test retired; the dispatch refresh below keeps the invariant.
"""

from __future__ import annotations

from typing import Any

import pytest
from connection_backed_admin_probes import blob_at_profile_address, document, marker
from connection_backed_oauth_probes import access_token_of, callback
from provider_access_harness import PROVIDER, ProfileBackedHarness
from test_writer_floor_refresh import (
    Intrusion,
    expired_blob,
    profile_service,
    resolve_and_authorize,
    use_intruding_tokens,
)

from aigateway.core.credential_names import profile_id_for
from aigateway.core.profile_models import ProfileState
from aigateway.core.provider_access import WriteConflict
from tests.unit.oauth_flow_seed import open_oauth_flow


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def a_reauth_start(h: Any, started: list[str]) -> Intrusion:
    """The user clicks re-auth on the same Profile while the refresh waits on the provider."""

    async def intrude() -> None:
        # WHY a seeder: the start route answers 410 since OME-1209 Stage E3; its callback still
        # completes a flow opened before the deploy, which is what this intrusion stands for.
        started.append(
            await open_oauth_flow(
                h.client.app, account_id=h.account_id, provider=PROVIDER, name="default"
            )
        )

    return intrude


def a_document_removal(h: Any) -> Intrusion:
    """A Profile document removed WITHOUT a pair claim — the owner fence alone must catch it."""

    async def intrude() -> None:
        await h.client.app.state.profile_index.remove(
            profile_id_for(h.account_id, PROVIDER, "default")
        )

    return intrude


def test_a_dispatch_refresh_leaves_a_reauth_started_in_its_window_pending(legacy) -> None:
    # INVARIANT (§5.3): the refresh stamps `last_refreshed_at` but never promotes a PENDING
    # document, so the re-auth callback still finds the pending flow it started.
    h = legacy
    h.seed_profile()
    h.blobs.write(profile_service(h), "default", expired_blob())
    started: list[str] = []
    use_intruding_tokens(h, ["fresh-tok", "reauthed"], a_reauth_start(h, started))

    resolve_and_authorize(h)

    assert started
    doc = document(h)
    assert doc is not None and doc.state == ProfileState.PENDING
    resp = callback(h, started[0])
    assert resp.status_code < 400, resp.text
    assert access_token_of(blob_at_profile_address(h)) == "reauthed"


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
