"""Row 11 — the legacy OAuth shadow proven by identity (OME-1497, G1 part 3).

# FEATURE: OME-1138 D18 (contract §5 row 11, §5.1 "Legacy OAuth shadow — identity proof", §8) — a
# legacy OAuth callback on a `none` pair writes a Profile and a shadow Connection at a different
# (UUID) locator. PUT and DELETE manage that pair only when both OAuth identities exist and match.
# STORY: as an operator, I replace or disconnect a tenant's OAuth credential that a legacy login
# left as a Profile plus its shadow Connection, without an operator repair.
# INVARIANT: the proof compares identities, never blobs — the Profile path refreshes and rotates
# only its own address, so the two blobs differ in steady state.
# INVARIANT: a refused or superseded mutation writes nothing and (refused) runs no key check.
# NOTE: `extract_identity` is stubbed on the served plugin; the real extractors are the callback's
# own and are covered by the plugin tests.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pair_shadow_harness import (
    NEW_KEY,
    PROFILE,
    PROVIDER,
    RAISING_TOKEN,
    SUB,
    ProfileBackedHarness,
    _address,
    _delete,
    _documents,
    _marker,
    _put,
    _raw,
    _rows,
    _shadow,
    _state,
    stub_identity,
)

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.provider_access import (
    PairAuthorityStore,
    PairNotManageable,
    pair_inventory,
)
from aigateway.core.secrets.mixin import SecretDecryptionError


@pytest.fixture
def harness(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def extracted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    return stub_identity(monkeypatch)


# --- the proof holds ------------------------------------------------------------------------


@pytest.mark.parametrize("token", ["profile-token", "rotated-profile-token"])
def test_put_on_a_proven_shadow_publishes_through_the_connection(harness, extracted, token) -> None:
    shadow = _shadow(harness, profile_token=token)

    mutation = _put(harness)

    (row,) = _rows(harness)
    assert (row["id"], row["status"], row["auth_type"]) == (shadow.id, "active", "api_key")
    assert row["credential_locator"] == shadow.credential_locator
    assert _marker(harness) == {
        "migration_state": "migrated",
        "effective_connection_id": shadow.id,
        "generation": 1,
    }
    assert json.loads(_raw(harness, shadow.credential_locator) or "{}")["api_key"] == NEW_KEY
    # The Profile is retired as an owner: its document stays only as the private mirror, under
    # its own name (no second `default` document), and its OAuth blob is gone.
    assert _documents(harness) == [PROFILE]
    assert _raw(harness, _address(harness, PROFILE)) is None
    assert mutation.credential is not None
    assert mutation.credential.credential_state == "active"
    assert mutation.connection_ids == (str(shadow.id),)
    assert PROFILE in mutation.profile_names
    # The proof decrypted the Profile blob in process — the token the callback's extractor reads.
    assert {c["access_token"] for c in extracted} == {token}


def test_the_successor_list_then_shows_the_one_credential(harness, extracted) -> None:
    _shadow(harness)
    before = harness.call(pair_inventory, harness.client.app, harness.account_id)
    assert [c.kind for c in before.conflicts] == ["unresolved"]
    assert extracted == [], "LIST never decrypts or proves"

    _put(harness)

    after = harness.call(pair_inventory, harness.client.app, harness.account_id)
    assert (len(after.credentials), after.conflicts) == (1, ())


def test_delete_on_a_proven_shadow_retires_both_owners_and_both_blobs(harness, extracted) -> None:
    shadow = _shadow(harness, profile_token="rotated-profile-token")

    mutation = _delete(harness)

    (row,) = _rows(harness)
    assert (row["id"], row["status"]) == (shadow.id, "revoked")
    assert _marker(harness) == {
        "migration_state": "migrated",
        "effective_connection_id": None,
        "generation": 1,
    }
    assert _documents(harness) == []
    assert _raw(harness, shadow.credential_locator) is None
    assert _raw(harness, _address(harness, PROFILE)) is None
    assert mutation.credential is None
    assert (mutation.profile_names, mutation.connection_ids) == ((PROFILE,), (str(shadow.id),))


# --- the proof fails: 409 unresolved, nothing written, no key check ---------------------------


def _no_profile_identity(harness: ProfileBackedHarness) -> OAuthConnection:
    return _shadow(harness, profile_token="unknown-token")


def _no_connection_identity(harness: ProfileBackedHarness) -> OAuthConnection:
    return _shadow(harness, identity_sub=None)


def _different_identities(harness: ProfileBackedHarness) -> OAuthConnection:
    return _shadow(harness, profile_token="other-token")


def _undecodable_profile_blob(harness: ProfileBackedHarness) -> OAuthConnection:
    shadow = _shadow(harness)
    address = _address(harness, PROFILE)
    harness.blobs.write(address["service"], address["account"], "not json {")
    return shadow


def _non_object_profile_blob(harness: ProfileBackedHarness) -> OAuthConnection:
    shadow = _shadow(harness)
    address = _address(harness, PROFILE)
    harness.blobs.write(address["service"], address["account"], json.dumps(["profile-token"]))
    return shadow


def _missing_profile_blob(harness: ProfileBackedHarness) -> OAuthConnection:
    shadow = _shadow(harness)
    address = _address(harness, PROFILE)
    harness.blobs.delete(address["service"], address["account"])
    return shadow


def _extractor_raises(harness: ProfileBackedHarness) -> OAuthConnection:
    return _shadow(harness, profile_token=RAISING_TOKEN)


def _undecryptable_profile_blob(harness: ProfileBackedHarness) -> OAuthConnection:
    shadow = _shadow(harness)
    store = harness.client.app.state.credential_store
    address = _address(harness, PROFILE)
    real = store.read

    async def read(service: str, account: str) -> str | None:
        if (service, account) == (address["service"], address["account"]):
            raise SecretDecryptionError("failed to decrypt credential blob")
        return await real(service, account)

    harness.monkeypatch.setattr(store, "read", read)
    return shadow


def _api_key_connection_with_a_sub(harness: ProfileBackedHarness) -> OAuthConnection:
    shadow = _shadow(harness)

    async def to_api_key() -> None:
        await OAuthConnection.filter(id=shadow.id).update(auth_type="api_key")

    harness.call(to_api_key)
    return shadow


def _migrated_null_beside_a_shadow(harness: ProfileBackedHarness) -> OAuthConnection:
    shadow = _shadow(harness)

    async def advance() -> None:
        current = await PairAuthorityStore().read(harness.account_id, PROVIDER)
        await PairAuthorityStore().advance(
            harness.account_id,
            PROVIDER,
            expected_generation=current.generation,
            migration_state="migrated",
            effective_connection_id=None,
        )

    harness.call(advance)
    return shadow


@pytest.mark.parametrize(
    "seed",
    [
        _no_profile_identity,
        _no_connection_identity,
        _different_identities,
        _undecodable_profile_blob,
        _non_object_profile_blob,
        _missing_profile_blob,
        _extractor_raises,
        _undecryptable_profile_blob,
        _api_key_connection_with_a_sub,
        _migrated_null_beside_a_shadow,
    ],
    ids=[
        "profile-identity-missing",
        "connection-identity-missing",
        "different-identities",
        "undecodable-blob",
        "non-object-blob",
        "missing-blob",
        "extractor-raises",
        "undecryptable-blob",
        "api-key-connection",
        "migrated-null-is-never-proven",
    ],
)
@pytest.mark.parametrize("operation", ["put", "delete"])
def test_an_unproven_shadow_stays_unresolved_and_writes_nothing(
    harness, extracted, seed, operation
) -> None:
    shadow = seed(harness)
    before = _state(harness, shadow)
    validated: list[bool] = []

    async def validate() -> None:
        validated.append(True)

    with pytest.raises(PairNotManageable) as refused:
        if operation == "put":
            _put(harness, validate=validate)
        else:
            _delete(harness)

    assert (refused.value.provider, refused.value.kind) == (PROVIDER, "unresolved")
    # INVARIANT: no exception rides along — a failed extraction may hold the decrypted token.
    assert (refused.value.__cause__, refused.value.__context__) == (None, None)
    assert validated == []
    assert _state(harness, shadow) == before


@pytest.mark.parametrize("seed", [_different_identities, _extractor_raises])
def test_a_refusal_never_carries_decrypted_data(harness, extracted, caplog, seed) -> None:
    seed(harness)

    with pytest.raises(PairNotManageable) as refused:
        _put(harness)

    rendered = f"{refused.value!r} {refused.value} {refused.value.__cause__!r} {caplog.text}"
    for secret in ("other-token", RAISING_TOKEN, "account-sub-2", SUB, "shadow-token"):
        assert secret not in rendered
