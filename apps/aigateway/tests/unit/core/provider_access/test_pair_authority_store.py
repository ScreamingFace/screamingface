"""The pair authority marker's store (OME-1208, Stage B S1; card v4 "Stage B Target").

# FEATURE: OME-1138 Stage B — one persistent row per `(account, provider)` says which backing owns
# the pair (`none` = legacy Profile, `migrated` = Connection, `quarantined` = legacy Profile plus a
# report) and which Connection is effective.
# INVARIANT: an absent row reads as `none` with generation 0; every authority-changing write
# advances the monotonic generation through a compare-and-set, so a stale writer — an old callback,
# a retried backfill — is fenced at commit time and changes nothing; an effective Connection is
# meaningful only for a `migrated` pair; the row carries no defaults and no secret.
# AIDEV-NOTE: the store is deliberately policy-free. WHICH transition a pair may take (classify,
# quarantine, roll back) is decided by the migration tool (S4) and the authority routing (S2');
# this file pins the fence and the shape those callers rely on.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import pytest
import pytest_asyncio
from tortoise.contrib.test import tortoise_test_context
from tortoise.exceptions import IntegrityError

from aigateway.core.auth.models import Account
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.provider_access.models import ProviderCredentialSlot
from aigateway.core.provider_access.pair_authority import (
    MIGRATION_STATES,
    MigrationState,
    PairAuthority,
    PairAuthorityConflict,
    PairAuthorityStore,
)

_MODELS = [
    "aigateway.core.auth.models",
    "aigateway.core.oauth.models",
    "aigateway.core.provider_access.models",
]
PROVIDER = "anthropic"
OTHER_PROVIDER = "codex"


@pytest_asyncio.fixture
async def accounts() -> AsyncIterator[tuple[Account, Account]]:
    async with tortoise_test_context(_MODELS):
        alice = await Account.create(username="alice", password_hash="hash")
        bob = await Account.create(username="bob", password_hash="hash")
        yield alice, bob


async def _active_connection(account: Account, *, label: str = "default") -> OAuthConnection:
    store = OAuthConnectionStore()
    pending = await store.create_pending(
        account_id=account.id, provider=PROVIDER, label=label, connection_id=uuid4()
    )
    return await store.complete(pending, label=label, identity=None)


def _legacy(account: Account, provider: str = PROVIDER) -> PairAuthority:
    return PairAuthority(
        account_id=str(account.id),
        provider=provider,
        migration_state="none",
        effective_connection_id=None,
        generation=0,
        migration_note=None,
    )


@pytest.mark.asyncio
async def test_an_absent_row_reads_as_legacy_authority(accounts: tuple[Account, Account]) -> None:
    alice, _ = accounts
    store = PairAuthorityStore()

    assert await store.read(str(alice.id), PROVIDER) == _legacy(alice)
    assert await store.list(str(alice.id)) == ()
    assert await ProviderCredentialSlot.all().count() == 0


@pytest.mark.asyncio
async def test_the_first_advance_creates_the_row_at_generation_one(
    accounts: tuple[Account, Account],
) -> None:
    alice, _ = accounts
    connection = await _active_connection(alice)
    store = PairAuthorityStore()

    published = await store.advance(
        str(alice.id),
        PROVIDER,
        expected_generation=0,
        migration_state="migrated",
        effective_connection_id=connection.id,
    )

    assert published == PairAuthority(
        account_id=str(alice.id),
        provider=PROVIDER,
        migration_state="migrated",
        effective_connection_id=connection.id,
        generation=1,
        migration_note=None,
    )
    assert await store.read(str(alice.id), PROVIDER) == published
    assert await ProviderCredentialSlot.all().count() == 1


@pytest.mark.asyncio
async def test_a_stale_generation_is_fenced_and_changes_nothing(
    accounts: tuple[Account, Account],
) -> None:
    alice, _ = accounts
    connection = await _active_connection(alice)
    store = PairAuthorityStore()
    first = await store.advance(
        str(alice.id),
        PROVIDER,
        expected_generation=0,
        migration_state="migrated",
        effective_connection_id=connection.id,
    )

    # A retried backfill that still believes the pair is unmarked.
    with pytest.raises(PairAuthorityConflict):
        await store.advance(
            str(alice.id),
            PROVIDER,
            expected_generation=0,
            migration_state="quarantined",
            migration_note="stale writer",
        )
    # A writer that never observed the row's real generation.
    with pytest.raises(PairAuthorityConflict):
        await store.advance(str(alice.id), PROVIDER, expected_generation=7, migration_state="none")
    assert await store.read(str(alice.id), PROVIDER) == first

    # R1 rollback: the owner resets the marker; every blob stays where it is (nothing here
    # touches a blob at all).
    rolled_back = await store.advance(
        str(alice.id), PROVIDER, expected_generation=1, migration_state="none"
    )
    assert rolled_back.generation == 2
    assert rolled_back.migration_state == "none"
    assert rolled_back.effective_connection_id is None
    # The writer that observed generation 1 lost the race and is fenced.
    with pytest.raises(PairAuthorityConflict):
        await store.advance(
            str(alice.id),
            PROVIDER,
            expected_generation=1,
            migration_state="migrated",
            effective_connection_id=connection.id,
        )
    assert await store.read(str(alice.id), PROVIDER) == rolled_back


@pytest.mark.asyncio
async def test_quarantine_keeps_legacy_authority_and_carries_the_report(
    accounts: tuple[Account, Account],
) -> None:
    alice, _ = accounts
    store = PairAuthorityStore()

    quarantined = await store.advance(
        str(alice.id),
        PROVIDER,
        expected_generation=0,
        migration_state="quarantined",
        migration_note="profile and connection hold different credentials",
    )

    assert quarantined.migration_state == "quarantined"
    assert quarantined.effective_connection_id is None
    assert quarantined.migration_note == "profile and connection hold different credentials"
    assert await store.read(str(alice.id), PROVIDER) == quarantined


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("migration_state", "with_connection"),
    [("none", True), ("quarantined", True), ("bogus", False)],
    ids=["none-with-effective", "quarantined-with-effective", "unknown-state"],
)
async def test_an_invalid_marker_is_refused_before_anything_is_written(
    accounts: tuple[Account, Account], migration_state: str, with_connection: bool
) -> None:
    # INVARIANT: only a `migrated` pair names an effective Connection — for `none` and
    # `quarantined` the legacy Profile owns the pair and a reference would be a second owner.
    alice, _ = accounts
    connection = await _active_connection(alice)
    store = PairAuthorityStore()

    with pytest.raises(ValueError):
        await store.advance(
            str(alice.id),
            PROVIDER,
            expected_generation=0,
            migration_state=cast(MigrationState, migration_state),
            effective_connection_id=connection.id if with_connection else None,
        )

    assert await store.read(str(alice.id), PROVIDER) == _legacy(alice)


@pytest.mark.asyncio
async def test_a_migrated_pair_may_hold_no_effective_connection_after_a_delete(
    accounts: tuple[Account, Account],
) -> None:
    # WHY: op 9 on a migrated pair removes the credential but NOT the ownership — falling back to
    # `none` would let the still-AUTHENTICATED legacy index entry (kept as a defaults-only document
    # under D16 (a)) serve the old credential again, the exact "reappears later" bad state.
    alice, _ = accounts
    connection = await _active_connection(alice)
    store = PairAuthorityStore()
    await store.advance(
        str(alice.id),
        PROVIDER,
        expected_generation=0,
        migration_state="migrated",
        effective_connection_id=connection.id,
    )

    emptied = await store.advance(
        str(alice.id), PROVIDER, expected_generation=1, migration_state="migrated"
    )

    assert emptied.migration_state == "migrated"
    assert emptied.effective_connection_id is None
    assert emptied.generation == 2


@pytest.mark.asyncio
async def test_pairs_are_isolated_by_account_and_by_provider(
    accounts: tuple[Account, Account],
) -> None:
    alice, bob = accounts
    connection = await _active_connection(alice)
    store = PairAuthorityStore()
    migrated = await store.advance(
        str(alice.id),
        PROVIDER,
        expected_generation=0,
        migration_state="migrated",
        effective_connection_id=connection.id,
    )

    # INVARIANT (tenant isolation): bob's pair and alice's other provider are untouched.
    assert await store.read(str(bob.id), PROVIDER) == _legacy(bob)
    assert await store.read(str(alice.id), OTHER_PROVIDER) == _legacy(alice, OTHER_PROVIDER)
    assert await store.list(str(alice.id)) == (migrated,)
    assert await store.list(str(bob.id)) == ()

    # The database enforces one marker per pair even for a writer that bypasses the store.
    with pytest.raises(IntegrityError):
        await ProviderCredentialSlot.create(
            account=alice, provider=PROVIDER, generation=9, migration_state="none"
        )


@pytest.mark.asyncio
async def test_deleting_the_effective_connection_clears_the_reference_and_keeps_ownership(
    accounts: tuple[Account, Account],
) -> None:
    # WHY a database-level SET NULL: the application path (S2') clears the reference in the same
    # transaction before the row goes; this is the safety net for a writer that does not.
    alice, _ = accounts
    connection = await _active_connection(alice)
    store = PairAuthorityStore()
    await store.advance(
        str(alice.id),
        PROVIDER,
        expected_generation=0,
        migration_state="migrated",
        effective_connection_id=connection.id,
    )

    await OAuthConnection.filter(id=connection.id).delete()

    after = await store.read(str(alice.id), PROVIDER)
    assert after.effective_connection_id is None
    assert after.migration_state == "migrated"
    assert after.generation == 1


@pytest.mark.asyncio
async def test_deleting_the_account_cascades_its_markers_only(
    accounts: tuple[Account, Account],
) -> None:
    alice, bob = accounts
    store = PairAuthorityStore()
    await store.advance(
        str(alice.id), PROVIDER, expected_generation=0, migration_state="quarantined"
    )
    kept = await store.advance(
        str(bob.id), PROVIDER, expected_generation=0, migration_state="quarantined"
    )

    await Account.filter(id=alice.id).delete()

    assert await ProviderCredentialSlot.filter(account_id=alice.id).count() == 0
    assert await store.read(str(bob.id), PROVIDER) == kept


def test_the_marker_carries_no_defaults_and_no_secret() -> None:
    # INVARIANT (D2, card v4): the row says who owns the pair and nothing else.
    assert set(ProviderCredentialSlot._meta.fields_map) <= {
        "id",
        "provider",
        "generation",
        "migration_state",
        "migration_note",
        "updated_at",
        "account",
        "account_id",
        "effective_connection",
        "effective_connection_id",
    }
    assert ProviderCredentialSlot._meta.db_table == "provider_credential_slots"
    assert MIGRATION_STATES == frozenset({"none", "migrated", "quarantined"})
