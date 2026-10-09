"""G0 refresh guard — a refresh loses only when its OWN credential moved (OME-1497, §5.3).

# FEATURE: OME-1138 D18, G0 part 2 (contract §5.3, owner decision 2026-10-07) — the publication
# checks the owner and the revision of the blob it refreshed, not the pair-wide generation. An
# ownership change elsewhere on the pair (another Connection created or started) no longer burns a
# rotating refresh token; anything that rewrote, deleted or recreated this blob still wins.
# AIDEV-NOTE: helpers are bound from `test_writer_floor_refresh`; intrusions run inside the
# refresh's provider window on the app loop.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from connection_backed_admin_probes import (
    blob_at_connection_address,
    blob_at_profile_address,
    marker,
)
from connection_backed_oauth_probes import access_token_of
from provider_access_harness import ProfileBackedHarness
from test_writer_floor_refresh import (
    Intrusion,
    an_ownership_claim,
    connection_service,
    expired_blob,
    nothing,
    profile_service,
    resolve_and_authorize,
    use_intruding_tokens,
)

from aigateway.core.credential_blob.model import CredentialBlob
from aigateway.core.provider_access import WriteConflict
from aigateway.plugins.anthropic_provider.auth import AnthropicOAuth


@pytest.fixture
def legacy(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def valid_blob(token: str) -> str:
    return json.dumps(
        {
            "access_token": token,
            "refresh_token": f"rt-{token}",
            "token_type": "Bearer",
            "expires_at_ms": int(time.time() * 1000) + 3_600_000,
        }
    )


def a_credential_rewrite(h: Any, service: str, value: str) -> Intrusion:
    """Another writer replaced THIS blob's credential (a re-auth callback, a key replacement)."""

    async def intrude() -> None:
        await h.client.app.state.credential_store.write(service, "default", value)

    return intrude


def a_blob_recreation(h: Any, service: str) -> Intrusion:
    """The blob was deleted and written again until it reached the captured revision — same
    address and revision, a new row."""

    async def revision() -> int:
        row = await CredentialBlob.filter(service=service, account="default").first()
        assert row is not None
        return row.credential_revision

    async def intrude() -> None:
        captured = await revision()
        await CredentialBlob.filter(service=service, account="default").delete()
        store = h.client.app.state.credential_store
        await store.write(service, "default", expired_blob("other"))
        while await revision() < captured:
            await store.write(service, "default", expired_blob("other"))

    return intrude


# --- the false loss the pair-wide check caused ------------------------------------------------


def test_a_dispatch_refresh_survives_an_ownership_change_elsewhere_on_the_pair(legacy) -> None:
    # INVARIANT (§5.3, owner decision 2026-10-07): another writer's claim on the pair does not
    # touch this blob, so the rotated refresh token is published and not burned.
    h = legacy
    h.seed_profile()
    h.blobs.write(profile_service(h), "default", expired_blob())
    use_intruding_tokens(h, "fresh-tok", an_ownership_claim(h))

    resolve_and_authorize(h)

    assert access_token_of(blob_at_profile_address(h)) == "fresh-tok"
    assert marker(h).generation == 1


def test_a_token_refresh_survives_an_ownership_change_elsewhere_on_the_pair(legacy) -> None:
    h = legacy
    connection_id = h.seed_connection(label="work")
    h.blobs.write(connection_service(h, connection_id), "default", expired_blob())
    use_intruding_tokens(h, "fresh-tok", an_ownership_claim(h))

    resp = h.client.get(f"/v1/oauth/connections/{connection_id}/token")

    assert resp.status_code == 200, resp.text
    assert access_token_of(blob_at_connection_address(h, connection_id)) == "fresh-tok"


# --- this blob moved: the refresh still loses -------------------------------------------------


def test_a_token_refresh_loses_to_a_rewrite_of_its_own_blob(legacy) -> None:
    h = legacy
    connection_id = h.seed_connection(label="work")
    service = connection_service(h, connection_id)
    h.blobs.write(service, "default", expired_blob())
    use_intruding_tokens(h, "fresh-tok", a_credential_rewrite(h, service, expired_blob("new")))

    resp = h.client.get(f"/v1/oauth/connections/{connection_id}/token")

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "connection_conflict"
    assert access_token_of(blob_at_connection_address(h, connection_id)) == "new"


def test_a_dispatch_refresh_loses_to_a_recreated_blob_at_its_address(legacy) -> None:
    # WHY: a recreated row starts again at revision 1, so the row id is part of the observation.
    h = legacy
    h.seed_profile()
    service = profile_service(h)
    h.blobs.write(service, "default", expired_blob())
    use_intruding_tokens(h, "fresh-tok", a_blob_recreation(h, service))

    with pytest.raises(WriteConflict):
        resolve_and_authorize(h)

    assert access_token_of(blob_at_profile_address(h)) == "other"


def test_a_cached_strategy_does_not_resurrect_a_blob_deleted_before_its_refresh(legacy) -> None:
    # INVARIANT: a strategy serving cached tokens refreshes from memory; if its blob is gone when
    # the refresh starts, publishing would bring a deleted credential back.
    h = legacy
    connection_id = h.seed_connection(label="work")
    service = connection_service(h, connection_id)
    h.blobs.write(service, "default", expired_blob())
    use_intruding_tokens(h, ["first", "second"], nothing(), expires_in=1)
    assert h.client.get(f"/v1/oauth/connections/{connection_id}/token").status_code == 200

    async def delete_the_blob() -> None:
        await CredentialBlob.filter(service=service, account="default").delete()

    h.call(delete_the_blob)

    resp = h.client.get(f"/v1/oauth/connections/{connection_id}/token")

    assert resp.status_code == 409, resp.text
    assert blob_at_connection_address(h, connection_id) is None


# --- the observation belongs to the credentials being refreshed --------------------------------


def test_a_cached_strategy_does_not_overwrite_a_credential_replaced_before_its_refresh(
    legacy,
) -> None:
    # INVARIANT (§5.3 "the credential it refreshed"): a strategy refreshes the tokens it loaded;
    # a rewrite committed after that load — even before the refresh starts — must win.
    h = legacy
    connection_id = h.seed_connection(label="work")
    service = connection_service(h, connection_id)
    h.blobs.write(service, "default", expired_blob())
    use_intruding_tokens(h, ["first", "second"], nothing(), expires_in=1)
    assert h.client.get(f"/v1/oauth/connections/{connection_id}/token").status_code == 200
    h.call(a_credential_rewrite(h, service, expired_blob("new")))

    resp = h.client.get(f"/v1/oauth/connections/{connection_id}/token")

    assert resp.status_code == 409, resp.text
    assert access_token_of(blob_at_connection_address(h, connection_id)) == "new"


def test_a_rewrite_between_the_credential_read_and_the_refresh_wins(
    legacy, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY the read itself: a fresh strategy reads the blob, then starts the refresh; a writer that
    # commits in between (here a valid, unexpired credential) must not be overwritten with the
    # tokens refreshed from what was read. Nor may it be refused: a 409 here would have spent the
    # NEW credential's rotating refresh token, so the strategy re-reads and serves it.
    h = legacy
    connection_id = h.seed_connection(label="work")
    service = connection_service(h, connection_id)
    h.blobs.write(service, "default", expired_blob())
    use_intruding_tokens(h, "fresh-tok", nothing())
    real_read = AnthropicOAuth._read_credential
    rewritten: list[bool] = []

    async def read_then_rewrite(self: Any) -> Any:
        creds = await real_read(self)
        if not rewritten:
            rewritten.append(True)
            await a_credential_rewrite(h, service, valid_blob("new"))()
        return creds

    monkeypatch.setattr(AnthropicOAuth, "_read_credential", read_then_rewrite)

    resp = h.client.get(f"/v1/oauth/connections/{connection_id}/token")

    assert rewritten
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"] == "new"
    assert access_token_of(blob_at_connection_address(h, connection_id)) == "new"


def test_a_credential_rewritten_under_every_read_is_not_refreshed(
    legacy, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: the bracketed read is bounded — a credential that never holds still is refused,
    # and no refresh spends its token.
    h = legacy
    connection_id = h.seed_connection(label="work")
    service = connection_service(h, connection_id)
    h.blobs.write(service, "default", expired_blob())
    use_intruding_tokens(h, "fresh-tok", nothing())
    real_read = AnthropicOAuth._read_credential
    reads: list[int] = []

    async def read_then_rewrite(self: Any) -> Any:
        creds = await real_read(self)
        reads.append(1)
        await a_credential_rewrite(h, service, expired_blob(f"churn-{len(reads)}"))()
        return creds

    monkeypatch.setattr(AnthropicOAuth, "_read_credential", read_then_rewrite)

    resp = h.client.get(f"/v1/oauth/connections/{connection_id}/token")

    assert resp.status_code == 409, resp.text
    assert len(reads) == 3
    assert access_token_of(blob_at_connection_address(h, connection_id)) == "churn-3"
