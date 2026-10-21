"""Post-review fail-closed regressions for the G1 pair inventory."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from provider_access_harness import PROVIDER, ProfileBackedHarness

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.provider_access import (
    CredentialAuthorityUnavailable,
    CredentialStoreReadUnavailable,
    MigrationState,
    PairAuthorityStore,
    PairConflict,
    PairInventory,
    classify_pair,
    pair_inventory,
    store_reads,
)
from aigateway.core.provider_access.models import ProviderCredentialSlot

UNKNOWN = "gone-plugin"


@pytest.fixture
def harness(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _inventory(harness: ProfileBackedHarness) -> PairInventory:
    return harness.call(pair_inventory, harness.client.app, harness.account_id)


def _mark(
    harness: ProfileBackedHarness,
    provider: str,
    state: MigrationState,
    *,
    effective: str | None = None,
) -> None:
    async def advance() -> None:
        current = await PairAuthorityStore().read(harness.account_id, provider)
        await PairAuthorityStore().advance(
            harness.account_id,
            provider,
            expected_generation=current.generation,
            migration_state=state,
            effective_connection_id=UUID(effective) if effective else None,
        )

    harness.call(advance)


def _unknown_connection(
    harness: ProfileBackedHarness,
    *,
    locator: dict[str, str] | None = None,
) -> str:
    connection_id = uuid4()
    harness.call(
        OAuthConnectionStore().create_api_key,
        account_id=harness.account_id,
        provider=UNKNOWN,
        label=f"unknown-{connection_id}",
        connection_id=connection_id,
        credential_provider=UNKNOWN,
        credential_locator=locator,
    )
    return str(connection_id)


def test_an_unknown_quarantined_pair_is_never_hidden_as_empty(harness) -> None:
    _mark(harness, UNKNOWN, "quarantined")

    assert _inventory(harness) == PairInventory(
        credentials=(), conflicts=(PairConflict(UNKNOWN, "unresolved"),)
    )


def test_an_unknown_migrated_pair_with_a_dangling_reference_is_unavailable(harness) -> None:
    effective = _unknown_connection(harness)
    _mark(harness, UNKNOWN, "migrated", effective=effective)

    async def revoke() -> None:
        from aigateway.core.oauth.models import OAuthConnection

        await OAuthConnection.filter(id=effective).update(status="revoked")

    harness.call(revoke)

    with pytest.raises(CredentialAuthorityUnavailable) as refused:
        _inventory(harness)

    assert refused.value.provider == UNKNOWN


def test_an_unknown_provider_with_an_out_of_scope_locator_is_unavailable(harness) -> None:
    _unknown_connection(
        harness,
        locator={
            "service": f"aigateway:{UNKNOWN}:another-account:key",
            "account": "default",
        },
    )

    with pytest.raises(CredentialAuthorityUnavailable) as refused:
        _inventory(harness)

    assert refused.value.provider == UNKNOWN


def test_an_unregistered_shipped_provider_keeps_its_stable_credential_namespace(
    harness,
) -> None:
    provider = "gemini-cli"
    marker = harness.call(PairAuthorityStore().read, harness.account_id, provider)
    connection = OAuthConnection(
        id=uuid4(),
        account_id=harness.account_id,
        provider=provider,
        label="legacy-gemini",
        status="active",
        auth_type="oauth",
        credential_locator=credential_locator_for("gemini", harness.account_id, "legacy-gemini"),
    )

    disposition = classify_pair(
        marker,
        [connection],
        credential_provider=None,
    )

    assert credential_service_provider_for(None, provider) == "gemini"
    assert disposition.row == 11


def test_inventory_retries_a_generation_move_instead_of_rendering_a_false_active(
    harness, monkeypatch
) -> None:
    harness.seed_connection(label="shadow")
    _mark(harness, PROVIDER, "migrated")
    real_list = OAuthConnectionStore.list
    connection_reads = 0
    snapshots = iter(
        [
            (),
            ((PROVIDER, 1),),
            ((PROVIDER, 1),),
            ((PROVIDER, 1),),
        ]
    )

    async def moving_connections(self: OAuthConnectionStore, *args: Any, **kwargs: Any):
        nonlocal connection_reads
        connection_reads += 1
        return [] if connection_reads == 1 else await real_list(self, *args, **kwargs)

    async def generations(_self: PairAuthorityStore, _account_id: str):
        return next(snapshots)

    monkeypatch.setattr(OAuthConnectionStore, "list", moving_connections)
    monkeypatch.setattr(PairAuthorityStore, "generations", generations, raising=False)

    assert _inventory(harness) == PairInventory(
        credentials=(), conflicts=(PairConflict(PROVIDER, "unresolved"),)
    )
    assert connection_reads == 2


def test_inventory_refuses_persistently_moving_generations(harness, monkeypatch) -> None:
    snapshots = iter([(), ((PROVIDER, 1),), ((PROVIDER, 1),), ((PROVIDER, 2),)])

    async def generations(_self: PairAuthorityStore, _account_id: str):
        return next(snapshots)

    monkeypatch.setattr(PairAuthorityStore, "generations", generations, raising=False)

    with pytest.raises(CredentialStoreReadUnavailable):
        _inventory(harness)


@pytest.mark.parametrize("generation", [0, -1])
def test_a_persisted_nonpositive_generation_is_unavailable(harness, generation) -> None:
    _mark(harness, PROVIDER, "none")

    async def corrupt() -> None:
        await ProviderCredentialSlot.filter(
            account_id=harness.account_id, provider=PROVIDER
        ).update(generation=generation)

    harness.call(corrupt)

    with pytest.raises(CredentialAuthorityUnavailable) as refused:
        _inventory(harness)

    assert refused.value.provider == PROVIDER


@pytest.mark.parametrize("error", [FileNotFoundError("missing"), PermissionError("denied")])
def test_a_non_database_oserror_is_not_disguised_as_a_store_outage(error) -> None:
    with pytest.raises(type(error)):
        with store_reads():
            raise error
