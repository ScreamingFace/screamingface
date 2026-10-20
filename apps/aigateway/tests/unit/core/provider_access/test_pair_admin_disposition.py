"""G1 pair disposition — the ordered §5 table behind the successor LIST (OME-1497, G1 part 1).

# FEATURE: OME-1138 D18 (contract §4, §5) — one result per provider: a neutral credential, a
# per-provider conflict, or nothing; a store or authority failure refuses the whole read.
# STORY: as an operator, I see exactly one credential per provider for an account, or an explicit
# reason why that provider cannot be managed safely — never several selectable names.
# INVARIANT: the first matching row decides; LIST never writes, never advances a marker and never
# reads a provider credential; unknown or inconsistent state is never rendered as `active` or as
# absence.
# NOTE: the inventory runs over the real stores. A state no writer can produce today (an
# unknown status, a malformed locator) is planted with a raw update — that is what row 2 is for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from asyncpg import exceptions as asyncpg_exceptions
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness
from tortoise.exceptions import OperationalError

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.provider_access import (
    CredentialAuthorityUnavailable,
    CredentialStoreReadUnavailable,
    MigrationState,
    PairAuthorityStore,
    PairConflict,
    PairConflictKind,
    PairCredential,
    PairInventory,
    pair_inventory,
)
from aigateway.core.provider_access.models import ProviderCredentialSlot
from aigateway.core.secrets.mixin import SecretDecryptionError

CREDENTIAL_PROVIDER = credential_service_provider_for(ANTHROPIC, PROVIDER)


@pytest.fixture
def harness(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _inventory(harness: ProfileBackedHarness) -> PairInventory:
    return harness.call(pair_inventory, harness.client.app, harness.account_id)


def _only(harness: ProfileBackedHarness) -> PairCredential | PairConflict | None:
    inventory = _inventory(harness)
    results = [*inventory.credentials, *inventory.conflicts]
    assert len(results) <= 1, results
    return results[0] if results else None


def _profile_address(harness: ProfileBackedHarness, name: str = "default") -> dict[str, str]:
    return credential_locator_for(CREDENTIAL_PROVIDER, harness.account_id, name)


def _api_key_connection(
    harness: ProfileBackedHarness,
    *,
    locator: dict[str, str] | None = None,
    provider: str = PROVIDER,
) -> str:
    connection_id = uuid4()
    harness.call(
        OAuthConnectionStore().create_api_key,
        account_id=harness.account_id,
        provider=provider,
        label=f"api-key-{connection_id}",
        connection_id=connection_id,
        credential_provider=CREDENTIAL_PROVIDER if provider == PROVIDER else None,
        credential_locator=locator,
    )
    return str(connection_id)


def _update_connection(harness: ProfileBackedHarness, connection_id: str, **fields: Any) -> None:
    async def update() -> None:
        await OAuthConnection.filter(id=connection_id).update(**fields)

    harness.call(update)


def _mark(
    harness: ProfileBackedHarness,
    state: MigrationState,
    *,
    effective: str | None = None,
    note: str | None = None,
) -> None:
    async def advance() -> None:
        current = await PairAuthorityStore().read(harness.account_id, PROVIDER)
        await PairAuthorityStore().advance(
            harness.account_id,
            PROVIDER,
            expected_generation=current.generation,
            migration_state=state,
            effective_connection_id=UUID(effective) if effective else None,
            migration_note=note,
        )

    harness.call(advance)


def _marker_rows(harness: ProfileBackedHarness) -> list[dict[str, Any]]:
    async def rows() -> list[dict[str, Any]]:
        return await ProviderCredentialSlot.filter(account_id=harness.account_id).values(
            "provider", "migration_state", "generation", "effective_connection_id"
        )

    return harness.call(rows)


def _conflict(kind: PairConflictKind) -> PairConflict:
    return PairConflict(provider=PROVIDER, kind=kind)


# --- rows 6 and 7: nothing to list ----------------------------------------------------------


def test_an_empty_account_lists_nothing(harness) -> None:
    assert _inventory(harness) == PairInventory(credentials=(), conflicts=())


def test_a_migrated_pair_with_no_effective_connection_lists_nothing(harness) -> None:
    # Row 6, with a leftover compatibility document: a read never resurrects it.
    harness.seed_profile(auth_type="api_key", credential="sk-ant-api03-left-over-0001")
    _mark(harness, "migrated")

    assert _only(harness) is None


# --- a listed owner's refresh time -------------------------------------------------------------


def test_a_listed_owner_carries_its_stored_refresh_time(harness) -> None:
    connection_id = _api_key_connection(harness)
    stamped = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    _update_connection(harness, connection_id, last_refreshed_at=stamped)

    listed = _only(harness)

    assert isinstance(listed, PairCredential)
    assert listed.last_refreshed_at == stamped


# --- row 9: the sole Connection -----------------------------------------------------------------


@pytest.mark.parametrize("status", ["active", "pending", "error"])
def test_a_connection_only_pair_lists_its_connection(harness, status) -> None:
    connection_id = _api_key_connection(harness)
    _update_connection(harness, connection_id, status=status)

    assert _only(harness) == PairCredential(
        provider=PROVIDER, auth_type="api_key", credential_state=status, last_refreshed_at=None
    )


def test_a_revoked_connection_is_not_listed(harness) -> None:
    connection_id = _api_key_connection(harness)
    _update_connection(harness, connection_id, status="revoked")

    assert _only(harness) is None


# --- row 3: more than one candidate -------------------------------------------------------------


def test_two_live_connections_are_ambiguous_even_on_a_migrated_pair(harness) -> None:
    effective = _api_key_connection(harness)
    _mark(harness, "migrated", effective=effective)
    stray = _api_key_connection(harness)
    _update_connection(harness, stray, status="pending")

    assert _only(harness) == _conflict("ambiguous")


# --- row 4: quarantine --------------------------------------------------------------------------


def test_a_quarantined_pair_is_unresolved_and_its_note_never_surfaces(harness) -> None:
    harness.seed_profile()
    _mark(harness, "quarantined", note="credentials_differ")

    conflict = _only(harness)

    assert conflict == _conflict("unresolved")
    assert "credentials_differ" not in repr(conflict)


# --- row 5: migrated with an effective reference ------------------------------------------------


@pytest.mark.parametrize("status", ["active", "pending", "error"])
def test_a_migrated_pair_lists_its_effective_connection(harness, status) -> None:
    # The compat mirror's state never decides: the effective Connection does.
    harness.seed_profile(auth_type="api_key", credential="sk-ant-api03-mirror-0004")
    effective = _api_key_connection(harness, locator=_profile_address(harness))
    _mark(harness, "migrated", effective=effective)
    _update_connection(harness, effective, status=status)

    assert _only(harness) == PairCredential(
        provider=PROVIDER, auth_type="api_key", credential_state=status, last_refreshed_at=None
    )


@pytest.mark.parametrize("make_unusable", ["revoke", "another_pair"])
def test_a_migrated_reference_to_a_revoked_or_missing_row_is_unavailable(
    harness, make_unusable
) -> None:
    effective = _api_key_connection(harness)
    _mark(harness, "migrated", effective=effective)
    if make_unusable == "revoke":
        _update_connection(harness, effective, status="revoked")
    else:
        # WHY another pair's row: the foreign key keeps a reference from dangling, so "missing"
        # is a reference this pair's live rows do not hold.
        _update_connection(harness, effective, provider="no-such-provider")

    with pytest.raises(CredentialAuthorityUnavailable) as refused:
        _inventory(harness)

    assert refused.value.provider == PROVIDER


def test_a_live_row_is_never_taken_for_a_revoked_reference(harness) -> None:
    # The pair's only live row is NOT the one the marker names: it is never shown in its place.
    effective = _api_key_connection(harness)
    _mark(harness, "migrated", effective=effective)
    _update_connection(harness, effective, status="revoked")
    _api_key_connection(harness)

    with pytest.raises(CredentialAuthorityUnavailable):
        _inventory(harness)


# --- row 2: unknown or inconsistent state -------------------------------------------------------


def _assert_authority_unavailable(harness: ProfileBackedHarness) -> None:
    with pytest.raises(CredentialAuthorityUnavailable) as refused:
        _inventory(harness)
    assert refused.value.provider == PROVIDER


def test_an_unknown_marker_state_is_unavailable(harness) -> None:
    harness.seed_profile()
    _mark(harness, "none")

    async def corrupt() -> None:
        await ProviderCredentialSlot.filter(account_id=harness.account_id).update(
            migration_state="adopted"
        )

    harness.call(corrupt)

    _assert_authority_unavailable(harness)


def test_a_reference_on_a_pair_that_is_not_migrated_is_unavailable(harness) -> None:
    connection_id = _api_key_connection(harness)
    _mark(harness, "none")

    async def corrupt() -> None:
        await ProviderCredentialSlot.filter(account_id=harness.account_id).update(
            effective_connection_id=UUID(connection_id)
        )

    harness.call(corrupt)

    _assert_authority_unavailable(harness)


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "unavailable"},
        {"auth_type": "bearer"},
        {"credential_locator": ["not", "a", "locator"]},
        {
            "credential_locator": {
                "service": "aigateway:anthropic:someone-else:x",
                "account": "default",
            }
        },
        {"credential_locator": {"service": "aigateway:openai:{account}:x", "account": "default"}},
        {"credential_locator": {"service": "aigateway:anthropic:{account}:x", "account": "other"}},
    ],
)
def test_an_unknown_or_out_of_scope_connection_is_unavailable(harness, fields) -> None:
    connection_id = _api_key_connection(harness)
    locator = fields.get("credential_locator")
    if isinstance(locator, dict):
        fields = {
            "credential_locator": {
                "service": locator["service"].format(account=harness.account_id),
                "account": locator["account"],
            }
        }
    _update_connection(harness, connection_id, **fields)

    _assert_authority_unavailable(harness)


def test_an_unknown_provider_is_an_explicit_unresolved_result(harness) -> None:
    _api_key_connection(harness, provider="no-such-provider")

    inventory = _inventory(harness)

    assert inventory == PairInventory(
        credentials=(),
        conflicts=(PairConflict(provider="no-such-provider", kind="unresolved"),),
    )


# --- row 1: the store cannot be read ------------------------------------------------------------


def test_an_unreadable_store_refuses_the_whole_inventory(harness, monkeypatch) -> None:
    _api_key_connection(harness)

    async def undecodable(*_args: Any, **_kwargs: Any) -> Any:
        raise SecretDecryptionError("failed to decrypt credential blob")

    # WHY the Connection read: LIST reads no Profile index since OME-1209 E4a.
    monkeypatch.setattr(OAuthConnectionStore, "list", undecodable)

    with pytest.raises(CredentialStoreReadUnavailable):
        _inventory(harness)


def test_a_programming_error_is_never_an_empty_inventory(harness, monkeypatch) -> None:
    async def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("a bug, not an outage")

    monkeypatch.setattr(OAuthConnectionStore, "list", broken)

    with pytest.raises(RuntimeError):
        _inventory(harness)


# --- ordering and side effects ------------------------------------------------------------------


def test_results_are_sorted_by_provider_and_one_per_provider(harness) -> None:
    _api_key_connection(harness, provider="zzz-unknown")
    _api_key_connection(harness)
    _api_key_connection(harness, provider="aaa-unknown")

    inventory = _inventory(harness)

    assert [c.provider for c in inventory.credentials] == [PROVIDER]
    assert [c.provider for c in inventory.conflicts] == ["aaa-unknown", "zzz-unknown"]


def test_the_inventory_writes_nothing_and_reads_no_credential(harness, monkeypatch) -> None:
    harness.seed_profile()
    _api_key_connection(harness)
    before = _marker_rows(harness)
    reads: list[tuple[str, str]] = []
    store = harness.client.app.state.credential_store
    real_read = store.read
    index_service = "aigateway:index"

    async def recording_read(service: str, account: str) -> Any:
        reads.append((service, account))
        return await real_read(service, account)

    monkeypatch.setattr(store, "read", recording_read)

    _inventory(harness)

    assert _marker_rows(harness) == before
    # Only the account's metadata index is read — never a provider credential blob.
    assert all(service.startswith(index_service) for service, _ in reads), reads


# --- review follow-ups: the unlisted migrated state, unknown providers, driver outages -----------


def test_a_migrated_pair_with_a_live_connection_but_no_reference_is_unresolved(harness) -> None:
    # No row of §5 matches (row 6 needs no live Connection); hiding the live row would break §4.
    _mark(harness, "migrated")
    _api_key_connection(harness)

    assert _only(harness) == _conflict("unresolved")


def test_a_disconnected_pair_of_an_unknown_provider_lists_nothing(harness) -> None:
    async def disconnect() -> None:
        await PairAuthorityStore().advance(
            harness.account_id,
            "gone-plugin",
            expected_generation=0,
            migration_state="migrated",
            effective_connection_id=None,
            migration_note=None,
        )

    harness.call(disconnect)

    assert _inventory(harness) == PairInventory(credentials=(), conflicts=())


def test_two_connections_of_an_unknown_provider_are_ambiguous(harness) -> None:
    _api_key_connection(harness, provider="no-such-provider")
    _api_key_connection(harness, provider="no-such-provider")

    assert _inventory(harness).conflicts == (
        PairConflict(provider="no-such-provider", kind="ambiguous"),
    )


def test_an_unknown_status_on_an_unknown_provider_is_unavailable(harness) -> None:
    connection_id = _api_key_connection(harness, provider="no-such-provider")
    _update_connection(harness, connection_id, status="unavailable")

    with pytest.raises(CredentialAuthorityUnavailable):
        _inventory(harness)


_DRIVER_OUTAGES = [
    asyncpg_exceptions.ConnectionDoesNotExistError("connection was closed"),
    asyncpg_exceptions.CannotConnectNowError("the database system is starting up"),
    asyncpg_exceptions.AdminShutdownError("terminating connection"),
    asyncpg_exceptions.TooManyConnectionsError("too many clients"),
    asyncpg_exceptions.InterfaceError("pool is closing"),
    ConnectionResetError("reset by peer"),
    TimeoutError(),
    OperationalError("server closed the connection"),
]


@pytest.mark.parametrize("outage", _DRIVER_OUTAGES, ids=lambda exc: type(exc).__name__)
@pytest.mark.parametrize("read", ["connections", "marker"])
def test_a_driver_outage_on_any_read_refuses_the_whole_inventory(
    harness, monkeypatch, outage, read
) -> None:
    _api_key_connection(harness)

    async def down(*_args: Any, **_kwargs: Any) -> Any:
        raise outage

    if read == "connections":
        monkeypatch.setattr(OAuthConnectionStore, "list", down)
    else:
        monkeypatch.setattr(PairAuthorityStore, "read", down)

    with pytest.raises(CredentialStoreReadUnavailable):
        _inventory(harness)
