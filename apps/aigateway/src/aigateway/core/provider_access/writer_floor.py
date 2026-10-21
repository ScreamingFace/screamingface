"""The G0 writer floor's pair primitives (OME-1497; D18 contract §5.3).

# FEATURE: OME-1138 D18, G0 — before the pair-addressed successor can adopt a `none` pair, every
# writer that changes who owns a pair claims the generation it observed: a writer that read the
# pair before another ownership change loses at commit time instead of overwriting it.
# INVARIANT: `claim_pair` re-publishes exactly the observed authority (state, effective reference,
# note) one generation later — it fences, it never changes the owner. `hold_pair` checks the
# observed generation under the marker row lock and never advances it.
# INVARIANT: call both inside the caller's `in_transaction()`, as the FIRST write, so the claim
# commits or rolls back with the data it fences (marker → row → blob). A lost claim is
# `PairAuthorityConflict`; under PostgreSQL the transaction is aborted by then, so callers catch it
# outside the `async with`.
"""

from __future__ import annotations

import logging
from typing import Any

from tortoise.transactions import in_transaction

from ..oauth.store import ensure_anonymous_account
from .models import ProviderCredentialSlot
from .pair_authority import (
    UNMARKED_GENERATION,
    PairAuthority,
    PairAuthorityConflict,
    PairAuthorityStore,
)

logger = logging.getLogger(__name__)


def fences_writer(pair: PairAuthority) -> bool:
    """True for the legacy-owned states whose writers G0 fences with the pair generation.

    # WHY not `migrated`: `claim_native_write` holds that marker without advancing it; effective
    # writes then advance it through their existing replacement/delete fence.
    """
    return pair.migration_state != "migrated"


async def claim_pair(observed: PairAuthority) -> PairAuthority:
    """Claim the observed generation for an ownership write, keeping what the marker says."""
    if observed.generation == UNMARKED_GENERATION:
        # WHY: the first marker's foreign key names the account; the anonymous account of
        # `auth_mode=disabled` is not stored until something needs it, and a missing row would
        # read as a false "superseded" conflict on every first write.
        await ensure_anonymous_account(observed.account_id)
    return await PairAuthorityStore().advance(
        observed.account_id,
        observed.provider,
        expected_generation=observed.generation,
        migration_state=observed.migration_state,
        effective_connection_id=observed.effective_connection_id,
        migration_note=observed.migration_note,
    )


async def claim_observed(observed: PairAuthority | None) -> PairAuthority | None:
    """Claim the pair a flow observed when the floor fences it: the published pair, else None.

    # WHY None passes through: a migrated pair is not claimed here (`fences_writer`); its repair
    # flow is fenced by `replace_effective`. A flow that captured nothing has nothing to claim.
    """
    if observed is None or not fences_writer(observed):
        return None
    return await claim_pair(observed)


async def hold_pair(observed: PairAuthority) -> None:
    """Check the observed generation without advancing it — the marker row stays locked to commit.

    Only for a marked pair: an absent marker has no row to lock, so a writer that must exclude a
    concurrent first marker claims instead.
    """
    if observed.generation == UNMARKED_GENERATION:
        raise ValueError("an unmarked pair cannot be held; claim it")
    # WHY a model-returning query: FOR UPDATE is dropped from `.values()` shapes in Tortoise.
    row = (
        await ProviderCredentialSlot.filter(
            account_id=observed.account_id, provider=observed.provider
        )
        .select_for_update()
        .first()
    )
    if row is None or row.generation != observed.generation:
        raise PairAuthorityConflict(observed.provider, observed.generation)


async def check_observed(observed: PairAuthority | None) -> None:
    """The §5.3 check for a writer that never changes the owner: the pair must not have moved.

    A marked pair is held at the observed generation. An unmarked observation has no row to lock,
    so it requires the marker to be still absent: one that appeared since is an ownership change.
    """
    if observed is None or not fences_writer(observed):
        return
    if observed.generation != UNMARKED_GENERATION:
        await hold_pair(observed)
        return
    appeared = (
        await ProviderCredentialSlot.filter(
            account_id=observed.account_id, provider=observed.provider
        )
        .select_for_update()
        .first()
    )
    if appeared is not None:
        raise PairAuthorityConflict(observed.provider, observed.generation)


async def observe_pair_of(connection: Any) -> PairAuthority:
    """The pair a Connection-owned flow observes before its provider call."""
    return await PairAuthorityStore().read(str(connection.account_id), connection.provider)


async def mark_error_checked(
    store: Any, connection: Any, message: str, *, observed: PairAuthority | None
) -> None:
    """Mark a Connection `error` only while its pair sits at the observed generation (§5.3).

    # WHY: an API-key Connection is re-keyed in place (same row, still `active`), so a stale
    # rejection of the old key would otherwise mark the new key `error`.
    # INVARIANT: a lost check marks nothing and never advances; the caller's answer is unchanged.
    # AIDEV-NOTE: nothing to check (no observation, or a `migrated` pair) marks exactly as before,
    # outside any transaction — the token service's store fakes rely on that.
    """
    if observed is None or not fences_writer(observed):
        await store.mark_error(connection, message)
        return
    try:
        async with in_transaction():
            await check_observed(observed)
            await store.mark_error(connection, message)
            # WHY re-check: on an unmarked pair there is no row to lock, so a first claim still
            # uncommitted at the check hides from it while its key write holds the Connection row;
            # the mark waits on that row, and this statement then sees the committed marker.
            await check_observed(observed)
    except PairAuthorityConflict:
        logger.info(
            "error mark skipped: %s pair moved since generation %d",
            observed.provider,
            observed.generation,
        )


__all__ = [
    "check_observed",
    "claim_observed",
    "claim_pair",
    "fences_writer",
    "hold_pair",
    "mark_error_checked",
    "observe_pair_of",
]
