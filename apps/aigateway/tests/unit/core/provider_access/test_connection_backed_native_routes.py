"""The Connection-native routes over a MIGRATED pair's effective row (OME-1208, S2'b4).

# FEATURE: Stage B Target — the effective Connection of a migrated pair is addressed at its
# `credential_locator` (the Profile blob) by EVERY path: refresh and token read/write THAT blob,
# key replacement writes it, delete evicts under its name (SF-282). The two authority-changing
# writes keep the pair coherent: delete retires the pair (op 9 shape), key replacement fences the
# generation and mirrors the compat document (op 8 shape).
# INVARIANT (D-S2b4-6): creating a SECOND Connection on a migrated provider never moves the
# marker — no silent authority change, no guessing between two credentials.
# AIDEV-NOTE: a stray (never-effective) row of a migrated pair is a plain Connection; the
# "stray" tests pin that the native routes leave the pair's authority alone for it.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest
from connection_backed_admin_probes import (
    KEY,
    blob_at_connection_address,
    blob_at_profile_address,
    connection,
    connections,
    document,
    marker,
    set_api_key,
)
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import (
    SENTINEL,
    access_token_of,
    status,
    use_failing_exchange,
    use_tokens,
)
from provider_access_harness import PROVIDER

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.oauth.store import credential_key_for
from aigateway.core.profile_index import ProfileTransitionConflict
from aigateway.core.profile_models import ProfileState, credential_name_for
from aigateway.core.provider_access.pair_authority import PairAuthorityConflict, PairAuthorityStore
from aigateway.plugins.anthropic_provider.auth import credential_service_for

OLD_KEY = "sk-ant-api03-migrated-old-key-1357"


@pytest.fixture
def migrated(authenticated_client, credential_blobs, monkeypatch) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def refresh(h: Any, connection_id: str) -> httpx.Response:
    return h.client.post(f"/v1/oauth/connections/{connection_id}/refresh")


def token(h: Any, connection_id: str) -> httpx.Response:
    return h.client.get(f"/v1/oauth/connections/{connection_id}/token")


def put_key(h: Any, connection_id: str, key: str = KEY) -> httpx.Response:
    return h.client.put(f"/v1/oauth/connections/{connection_id}/api-key", json={"api_key": key})


def delete(h: Any, connection_id: str) -> httpx.Response:
    return h.client.delete(f"/v1/oauth/connections/{connection_id}")


def patch_label(h: Any, connection_id: str, label: str) -> httpx.Response:
    return h.client.patch(f"/v1/oauth/connections/{connection_id}", json={"label": label})


def api_key_of(blob: str | None) -> str | None:
    return None if blob is None else json.loads(blob).get("api_key")


class _AcceptingValidation:
    """The explicit test double the unit conftest asks new modules for: every key is valid."""

    async def validate(self, _plugin: Any, _provider: str, _api_key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )


def accept_keys(h: Any) -> None:
    h.client.app.state.api_key_validation_service = _AcceptingValidation()


def lose_the_marker_fence(h: Any) -> None:
    """Every marker advance loses — the shape of a racing authority change on the pair."""

    async def losing_advance(*_args: Any, **_kwargs: Any) -> Any:
        raise PairAuthorityConflict(PROVIDER, 1)

    h.monkeypatch.setattr(PairAuthorityStore, "advance", losing_advance)


def locator_name(h: Any) -> str:
    return credential_name_for(h.account_id, "default")


def expire_the_locator_blob(h: Any) -> None:
    """The Profile blob with an already-expired access token — the token path MUST refresh."""
    h.blobs.write(
        credential_service_for(locator_name(h)),
        "default",
        json.dumps(
            {
                "access_token": "stale",
                "refresh_token": "rt",
                "token_type": "Bearer",
                "expires_at_ms": int(time.time() * 1000) - 1_000,
            }
        ),
    )


# --- refresh / token: the locator blob ------------------------------------------------------


def test_refresh_of_the_effective_row_rewrites_the_locator_blob(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    use_tokens(h, "fresh-tok")

    resp = refresh(h, effective)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert access_token_of(blob_at_profile_address(h)) == "fresh-tok"
    assert blob_at_connection_address(h, effective) is None
    row = connection(h, effective)
    assert row.status == "active" and row.last_refreshed_at is not None
    assert locator_name(h) in h.evicted()
    assert credential_key_for(h.account_id, effective) not in h.evicted()
    assert (marker(h).generation, str(marker(h).effective_connection_id)) == (1, effective)
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.AUTHENTICATED


def test_a_rejected_refresh_of_the_effective_row_marks_only_the_row(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    use_failing_exchange(h)

    resp = refresh(h, effective)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "auth_required"
    assert SENTINEL not in resp.text
    assert connection(h, effective).status == "error"
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    assert locator_name(h) in h.evicted()
    # D-S2b4-5: the shells render from the Connection; the document's state is not rewritten.
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.AUTHENTICATED
    assert status(h).json()["state"] == "error"


def test_token_of_the_effective_row_serves_the_locator_blob(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]

    resp = token(h, effective)

    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"] == "tok"
    assert connection(h, effective).status == "active"
    assert h.last_used(effective)


# --- delete: retire the pair ------------------------------------------------------------------


def test_deleting_the_effective_row_retires_the_pair(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]

    resp = delete(h, effective)

    assert resp.status_code == 204, resp.text
    assert connection(h, effective).status == "revoked"
    assert blob_at_profile_address(h) is None
    pair = marker(h)
    assert (pair.migration_state, pair.effective_connection_id, pair.generation) == (
        "migrated",
        None,
        2,
    )
    assert document(h) is None
    assert status(h).status_code == 404
    assert locator_name(h) in h.evicted()


def test_deleting_a_stray_row_leaves_the_pair_alone(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    stray = h.seed_connection(label="stray")

    resp = delete(h, stray)

    assert resp.status_code == 204, resp.text
    assert connection(h, stray).status == "revoked"
    assert connection(h, effective).status == "active"
    assert (marker(h).generation, str(marker(h).effective_connection_id)) == (1, effective)
    assert document(h) is not None
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    assert credential_key_for(h.account_id, stray) in h.evicted()


def test_deleting_the_effective_row_loses_to_a_racing_authority_change(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    lose_the_marker_fence(h)

    resp = delete(h, effective)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "connection_conflict"
    assert connection(h, effective).status == "active"
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    assert document(h) is not None
    assert marker(h).generation == 1


# --- api-key replacement: fence + mirror ------------------------------------------------------


def test_replacing_the_key_on_the_effective_row_fences_the_pair_and_mirrors(migrated) -> None:
    h = migrated
    accept_keys(h)
    h.seed_profile(auth_type="api_key", credential=OLD_KEY)
    effective = h.migrated["default"]

    resp = put_key(h, effective)

    assert resp.status_code == 200, resp.text
    assert (resp.json()["status"], resp.json()["auth_type"]) == ("active", "api_key")
    assert KEY not in resp.text
    assert api_key_of(blob_at_profile_address(h)) == KEY
    assert blob_at_connection_address(h, effective) is None
    pair = marker(h)
    assert (str(pair.effective_connection_id), pair.generation) == (effective, 2)
    doc = document(h)
    assert doc is not None
    assert (doc.auth_type, doc.state, doc.account_label) == (
        "api_key",
        ProfileState.AUTHENTICATED,
        f"API key ····{KEY[-4:]}",
    )
    assert locator_name(h) in h.evicted()
    assert status(h).json()["state"] == "authenticated"


def test_replacing_the_key_on_an_errored_effective_row_reactivates_it(migrated) -> None:
    h = migrated
    accept_keys(h)
    h.seed_profile(auth_type="api_key", state=ProfileState.ERROR, credential=OLD_KEY)
    effective = h.migrated["default"]
    assert status(h).json()["state"] == "error"

    resp = put_key(h, effective)

    assert resp.status_code == 200, resp.text
    assert connection(h, effective).status == "active"
    assert api_key_of(blob_at_profile_address(h)) == KEY
    assert status(h).json()["state"] == "authenticated"


def test_replacing_the_key_on_the_effective_row_loses_to_a_racing_authority_change(
    migrated,
) -> None:
    h = migrated
    accept_keys(h)
    h.seed_profile(auth_type="api_key", credential=OLD_KEY)
    effective = h.migrated["default"]
    lose_the_marker_fence(h)

    resp = put_key(h, effective)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "connection_conflict"
    assert api_key_of(blob_at_profile_address(h)) == OLD_KEY
    assert blob_at_connection_address(h, effective) is None
    assert marker(h).generation == 1


def test_replacing_the_key_on_a_stray_row_moves_no_marker(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    accept_keys(h)
    stray = h.seed_connection(label="stray-key", auth_type="api_key", credential=None)

    resp = put_key(h, stray)

    assert resp.status_code == 200, resp.text
    assert api_key_of(blob_at_connection_address(h, stray)) == KEY
    assert access_token_of(blob_at_profile_address(h)) == "tok"
    assert (marker(h).generation, str(marker(h).effective_connection_id)) == (1, effective)
    assert credential_key_for(h.account_id, stray) in h.evicted()


# --- metadata and creation: nothing moves -----------------------------------------------------


def test_patching_the_effective_row_label_is_metadata_only(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    before = document(h)
    assert before is not None

    resp = patch_label(h, effective, "renamed")

    assert resp.status_code == 200, resp.text
    assert connection(h, effective).label == "renamed"
    assert marker(h).generation == 1
    after = document(h)
    assert after is not None and after.model_dump() == before.model_dump()


def test_starting_a_second_connection_on_a_migrated_provider_moves_no_marker(migrated) -> None:
    """D-S2b4-6 characterisation: today's behaviour, pinned — the policy is the owner's call."""
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]

    resp = h.client.post("/v1/oauth/connections", json={"provider": PROVIDER, "label": "second"})

    assert resp.status_code == 201, resp.text
    assert resp.json()["connection_id"] != effective
    assert (marker(h).generation, str(marker(h).effective_connection_id)) == (1, effective)
    assert connection(h, effective).status == "active"
    assert {row.label for row in connections(h)} == {"default", "second"}


# --- coverage: the refresh window, documentless pairs, a vanished document, starting over ----


def test_token_of_the_effective_row_refreshes_into_the_locator_blob(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    expire_the_locator_blob(h)
    use_tokens(h, "minted")

    resp = token(h, effective)

    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"] == "minted"
    assert access_token_of(blob_at_profile_address(h)) == "minted"
    assert blob_at_connection_address(h, effective) is None
    row = connection(h, effective)
    assert row.status == "active" and row.last_refreshed_at is not None


def test_a_rejected_token_refresh_of_the_effective_row_marks_only_the_row(migrated) -> None:
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    expire_the_locator_blob(h)
    use_failing_exchange(h)

    resp = token(h, effective)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "auth_required"
    assert SENTINEL not in resp.text
    assert connection(h, effective).status == "error"
    doc = document(h)
    assert doc is not None and doc.state is ProfileState.AUTHENTICATED
    assert status(h).json()["state"] == "error"


def test_deleting_the_effective_row_of_a_documentless_pair_retires_it(migrated) -> None:
    h = migrated
    effective = h.seed_authority()

    resp = delete(h, effective)

    assert resp.status_code == 204, resp.text
    assert connection(h, effective).status == "revoked"
    pair = marker(h)
    assert (pair.migration_state, pair.effective_connection_id, pair.generation) == (
        "migrated",
        None,
        2,
    )
    assert document(h) is None


def test_replacing_the_key_loses_when_the_document_vanishes_in_the_window(migrated) -> None:
    h = migrated
    accept_keys(h)
    h.seed_profile(auth_type="api_key", credential=OLD_KEY)
    effective = h.migrated["default"]

    async def vanished(*_args: Any, **_kwargs: Any) -> Any:
        raise ProfileTransitionConflict("profile was concurrently deleted")

    h.monkeypatch.setattr(h.client.app.state.profile_index, "upsert", vanished)

    resp = put_key(h, effective)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "connection_conflict"
    assert api_key_of(blob_at_profile_address(h)) == OLD_KEY
    assert connection(h, effective).status == "active"
    # INVARIANT: one transaction — the marker advance rolled back with the failed mirror.
    assert marker(h).generation == 1


def test_after_a_native_delete_the_legacy_key_route_starts_over(migrated) -> None:
    """Post-delete shape = op 9's: op 8 mints a NEW effective Connection at the Profile address."""
    h = migrated
    h.seed_profile()
    effective = h.migrated["default"]
    assert delete(h, effective).status_code == 204

    set_api_key(h)

    pair = marker(h)
    assert pair.generation == 3
    assert pair.effective_connection_id is not None
    assert str(pair.effective_connection_id) != effective
    assert connection(h, effective).status == "revoked"
    assert api_key_of(blob_at_profile_address(h)) == KEY
    doc = document(h)
    assert doc is not None and doc.auth_type == "api_key"
    assert (status(h).json()["state"], status(h).json()["auth_type"]) == (
        "authenticated",
        "api_key",
    )
