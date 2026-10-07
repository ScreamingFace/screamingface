"""The G0 writer floor's pair primitives (OME-1497; D18 contract §5.3).

# FEATURE: OME-1138 D18, G0 — before the pair-addressed successor can adopt a `none` pair, every
# writer that changes who owns a pair claims the generation it observed, so a writer that read the
# pair before another ownership change loses instead of overwriting it.
# INVARIANT: a claim re-publishes exactly the observed authority (state, effective reference,
# note) one generation later — it fences, it never changes the owner; a hold checks the observed
# generation under the marker row lock and never advances it.
# INVARIANT: the first marker of the anonymous account is a normal claim, not a false conflict —
# in `auth_mode=disabled` the account row exists only after the first Connection, and the marker's
# foreign key names it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import pytest
import pytest_asyncio
from tortoise.contrib.test import tortoise_test_context

from aigateway.core.auth.middleware import ANONYMOUS_ACCOUNT_ID
from aigateway.core.auth.models import Account
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.provider_access.pair_authority import (
    MigrationState,
    PairAuthority,
    PairAuthorityConflict,
    PairAuthorityStore,
)
from aigateway.core.provider_access.writer_floor import claim_pair, fences_writer, hold_pair

_MODELS = [
    "aigateway.core.auth.models",
    "aigateway.core.oauth.models",
    "aigateway.core.provider_access.models",
]
PROVIDER = "anthropic"


@pytest_asyncio.fixture
async def account() -> AsyncIterator[Account]:
    async with tortoise_test_context(_MODELS):
        yield await Account.create(username="alice", password_hash="hash")


def _unmarked(account_id: str) -> PairAuthority:
    return PairAuthority(account_id, PROVIDER, "none", None, 0, None)


@pytest.mark.asyncio
async def test_a_claim_of_an_unmarked_pair_publishes_the_first_marker_as_none(
    account: Account,
) -> None:
    claimed = await claim_pair(_unmarked(str(account.id)))

    stored = await PairAuthorityStore().read(str(account.id), PROVIDER)
    assert stored == claimed
    assert (stored.migration_state, stored.generation) == ("none", 1)
    assert (stored.effective_connection_id, stored.migration_note) == (None, None)


@pytest.mark.asyncio
async def test_a_claim_keeps_a_quarantined_state_and_its_note(account: Account) -> None:
    observed = await PairAuthorityStore().advance(
        str(account.id),
        PROVIDER,
        expected_generation=0,
        migration_state="quarantined",
        migration_note="conflict",
    )

    claimed = await claim_pair(observed)

    assert (claimed.migration_state, claimed.generation, claimed.migration_note) == (
        "quarantined",
        2,
        "conflict",
    )
    assert await PairAuthorityStore().read(str(account.id), PROVIDER) == claimed


@pytest.mark.asyncio
async def test_a_claim_keeps_a_rollback_note_on_a_none_pair(account: Account) -> None:
    # WHY: an R1 rollback leaves `none` with the note `rollback`; a legacy write after it must
    # not erase the report (`advance` writes the note it is given, `None` by default).
    observed = await PairAuthorityStore().advance(
        str(account.id),
        PROVIDER,
        expected_generation=0,
        migration_state="none",
        migration_note="rollback",
    )

    claimed = await claim_pair(observed)

    assert (claimed.migration_state, claimed.migration_note) == ("none", "rollback")


@pytest.mark.asyncio
async def test_a_claim_keeps_the_effective_reference(account: Account) -> None:
    store = OAuthConnectionStore()
    pending = await store.create_pending(
        account_id=account.id, provider=PROVIDER, label="work", connection_id=uuid4()
    )
    connection = await store.complete(pending, label="work", identity=None)
    observed = await PairAuthorityStore().advance(
        str(account.id),
        PROVIDER,
        expected_generation=0,
        migration_state="migrated",
        effective_connection_id=connection.id,
    )

    claimed = await claim_pair(observed)

    assert (claimed.migration_state, claimed.effective_connection_id) == (
        "migrated",
        connection.id,
    )
    assert claimed.generation == observed.generation + 1


@pytest.mark.asyncio
async def test_a_stale_claim_loses_and_changes_nothing(account: Account) -> None:
    observed = _unmarked(str(account.id))
    winner = await claim_pair(observed)

    with pytest.raises(PairAuthorityConflict):
        await claim_pair(observed)

    assert await PairAuthorityStore().read(str(account.id), PROVIDER) == winner


@pytest.mark.asyncio
async def test_the_anonymous_account_claims_its_first_marker_without_a_false_conflict(
    account: Account,
) -> None:
    anonymous = str(ANONYMOUS_ACCOUNT_ID)
    assert await Account.filter(id=ANONYMOUS_ACCOUNT_ID).exists() is False

    claimed = await claim_pair(_unmarked(anonymous))

    assert (claimed.migration_state, claimed.generation) == ("none", 1)
    assert await Account.filter(id=ANONYMOUS_ACCOUNT_ID).exists() is True


@pytest.mark.asyncio
async def test_a_hold_accepts_the_observed_generation_and_never_advances(
    account: Account,
) -> None:
    observed = await claim_pair(_unmarked(str(account.id)))

    await hold_pair(observed)

    assert await PairAuthorityStore().read(str(account.id), PROVIDER) == observed


@pytest.mark.asyncio
async def test_a_hold_refuses_a_generation_another_writer_moved(account: Account) -> None:
    observed = await claim_pair(_unmarked(str(account.id)))
    await claim_pair(observed)

    with pytest.raises(PairAuthorityConflict):
        await hold_pair(observed)


@pytest.mark.parametrize(
    ("state", "fenced"),
    [("none", True), ("quarantined", True), ("migrated", False)],
)
def test_only_legacy_owned_pairs_take_the_new_writer_fence(state: str, fenced: bool) -> None:
    # WHY: a migrated pair's effective writes already advance the marker; its non-effective
    # native rows keep their existing fences (owner decision 2026-10-06).
    pair = PairAuthority("account", PROVIDER, cast(MigrationState, state), None, 3, None)

    assert fences_writer(pair) is fenced
