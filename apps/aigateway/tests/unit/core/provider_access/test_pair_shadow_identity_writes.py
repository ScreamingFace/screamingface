"""Row 11 — how a proven shadow mutation writes: atomically, evicting after commit, fenced.

# FEATURE: OME-1138 D18 (contract §5.1 step 3, §5.3) — the publication and the Profile's
# retirement are one transaction; a re-auth after the proof supersedes; cached credentials of both
# owners are dropped once the transaction is over.
# INVARIANT: a superseded or failed mutation writes nothing.
"""

from __future__ import annotations

from typing import Any

import pytest
from pair_shadow_harness import (
    ANTHROPIC,
    PROFILE,
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
from tortoise.exceptions import OperationalError

from aigateway.core.credential_names import credential_name_for
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.provider_access import (
    CredentialStoreUnavailable,
    WriteConflict,
)
from aigateway.core.provider_access.connection_native import credential_name_of


@pytest.fixture
def harness(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def extracted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    return stub_identity(monkeypatch)


def test_a_failure_retiring_the_profile_blob_rolls_the_whole_put_back(
    harness, extracted, monkeypatch
) -> None:
    """The Profile blob is retired inside the publication's transaction, never after it."""
    import aigateway.core.provider_access.pair_admin_writes as writes

    shadow = _shadow(harness)
    before = _state(harness, shadow)
    real = writes._delete_profile_blob

    async def delete_then_fail(*args: Any) -> str:
        await real(*args)
        raise OperationalError("connection lost")

    monkeypatch.setattr(writes, "_delete_profile_blob", delete_then_fail)

    with pytest.raises(CredentialStoreUnavailable):
        _put(harness)

    assert _state(harness, shadow) == before


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_both_owners_cached_credentials_are_dropped_after_the_commit(
    harness, extracted, monkeypatch, operation
) -> None:
    """Both names are evicted once the transaction is over — never only inside it.

    # WHY: an eviction inside the transaction can be refilled from the pre-commit state by a
    # concurrent dispatch. Retiring the Profile blob is the transaction's last write, so an
    # eviction recorded after it is a post-commit one.
    """
    import aigateway.core.provider_access.pair_admin_writes as writes
    from aigateway.core.credential_strategy_cache import credential_strategy_cache

    shadow = _shadow(harness)
    profile_name = credential_name_for(harness.account_id, PROFILE)
    connection_name = credential_name_of(ANTHROPIC, shadow, account_id=harness.account_id)
    retired: list[bool] = []
    after_retire: list[str] = []
    real_retire = writes._retire_shadow_profile

    async def retire(*args: Any) -> list[str]:
        names = await real_retire(*args)
        retired.append(True)
        return names

    cache = credential_strategy_cache(harness.client.app)
    real_evict = cache.evict

    def evict(credential_name: str) -> Any:
        if retired:
            after_retire.append(credential_name)
        return real_evict(credential_name)

    monkeypatch.setattr(writes, "_retire_shadow_profile", retire)
    monkeypatch.setattr(cache, "evict", evict)

    if operation == "put":
        _put(harness)
    else:
        _delete(harness)

    assert retired == [True]
    assert {profile_name, connection_name} <= set(after_retire)
    assert {profile_name, connection_name} <= set(harness.invalidated())


# --- a change after the proof supersedes ------------------------------------------------------


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_a_connection_identity_changed_after_the_proof_supersedes(
    harness, extracted, monkeypatch, operation
) -> None:
    """The transaction re-reads `identity_sub`; a re-auth to another account must not be adopted.

    # WHY wrap the proof: the change commits right after the LAST proof (PUT proves at both of
    # its captures), outside any transaction, as a racing re-auth would before the claim.
    """
    import aigateway.core.provider_access.pair_admin_writes as writes

    shadow = _shadow(harness)
    real = writes.prove_shadow
    proofs: list[bool] = []
    last_proof = 2 if operation == "put" else 1

    async def prove_then_reauth(app: Any, plugin: Any, disposition: Any) -> str:
        sub = await real(app, plugin, disposition)
        proofs.append(True)
        if len(proofs) == last_proof:
            await OAuthConnection.filter(id=shadow.id).update(identity_sub="account-sub-2")
        return sub

    monkeypatch.setattr(writes, "prove_shadow", prove_then_reauth)
    before_rows = [
        {**row, "identity_sub": "account-sub-2"} if row["id"] == shadow.id else row
        for row in _rows(harness)
    ]
    before = (_marker(harness), _documents(harness), _raw(harness, _address(harness, PROFILE)))

    with pytest.raises(WriteConflict) as lost:
        if operation == "put":
            _put(harness)
        else:
            _delete(harness)

    assert lost.value.kind == "superseded"
    assert len(proofs) == last_proof
    assert _rows(harness) == before_rows
    assert (_marker(harness), _documents(harness), _raw(harness, _address(harness, PROFILE))) == (
        before
    )
