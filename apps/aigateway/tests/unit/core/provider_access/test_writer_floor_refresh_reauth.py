"""G0 refresh guard on a legacy pair — re-auth in flight, and the owner presence fence (OME-1497).

# FEATURE: OME-1138 D18, G0 part 2 (contract §5.3) — "a refresh must not turn an in-flight re-auth
# callback into a false 409". A legacy re-auth start on an unmarked pair moves no marker; it only
# flips the document to PENDING, so the refresh's document stamp is what must leave it alone.
# AIDEV-NOTE: helpers are bound from `test_writer_floor_refresh`; the intrusion runs inside the
# refresh's provider window on the app loop.
"""

from __future__ import annotations

from typing import Any

import httpx
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

from aigateway.core.profile_models import ProfileState, profile_id_for
from aigateway.core.provider_access import WriteConflict


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def a_reauth_start(h: Any, started: list[httpx.Response]) -> Intrusion:
    """The user clicks re-auth on the same Profile while the refresh waits on the provider."""

    async def intrude() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=h.client.app),
            base_url=str(h.client.base_url),
            headers=dict(h.client.headers),
        ) as client:
            started.append(
                await client.post(f"/v1/auth/{PROVIDER}/profiles", json={"name": "default"})
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
    started: list[httpx.Response] = []
    use_intruding_tokens(h, ["fresh-tok", "reauthed"], a_reauth_start(h, started))

    resolve_and_authorize(h)

    assert started and started[0].status_code in (200, 201), started[0].text
    doc = document(h)
    assert doc is not None and doc.state == ProfileState.PENDING
    resp = callback(h, started[0].json()["state"])
    assert resp.status_code < 400, resp.text
    assert access_token_of(blob_at_profile_address(h)) == "reauthed"


def test_a_route_refresh_leaves_a_reauth_started_in_its_window_pending(legacy) -> None:
    h = legacy
    h.seed_profile()
    started: list[httpx.Response] = []
    use_intruding_tokens(h, ["fresh-tok", "reauthed"], a_reauth_start(h, started))

    refreshed = h.client.post(f"/v1/auth/{PROVIDER}/profiles/default/refresh")

    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["state"] == ProfileState.PENDING.value
    resp = callback(h, started[0].json()["state"])
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
