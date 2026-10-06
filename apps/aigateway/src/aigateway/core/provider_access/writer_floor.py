"""The G0 writer floor's pair primitives (OME-1497; D18 contract §5.3).

# FEATURE: OME-1138 D18, G0 — before the pair-addressed successor can adopt a `none` pair, every
# writer that changes who owns a pair claims the generation it observed: a writer that read the
# pair before another ownership change loses at commit time instead of overwriting it.
# INVARIANT: `claim_pair` re-publishes exactly the observed authority (state, effective reference,
# note) one generation later — it fences, it never changes the owner. `hold_pair` checks the
# observed generation under the marker row lock and never advances it.
# AIDEV-NOTE: call both inside the caller's `in_transaction()`, as the FIRST write, so the claim
# commits or rolls back with the data it fences (marker → index → row → blob). A lost claim is
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


class _NothingImported(Exception):
    """Rolls a startup import's claim back: an import that published nothing changed no owner."""


def fences_writer(pair: PairAuthority) -> bool:
    """True for the legacy-owned states whose writers G0 fences with the pair generation.

    # WHY not `migrated`: a migrated pair's effective writes already advance the marker, and its
    # non-effective native rows keep their existing fences (owner decision 2026-10-06).
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

    # WHY None passes through: a migrated flow is fenced by its own marker advance, and a flow
    # that captured nothing has nothing to claim.
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


async def bootstrap_under_the_floor(
    plugin: Any, *, account_id: str, credential_store: Any, index_store: Any
) -> None:
    """Run a provider's opt-in startup import as a legacy writer on its pair (§5.3 inventory).

    # WHY skip `migrated`: the pair's Connection owns the Profile address (D5) — an import there
    # would overwrite or shadow the effective credential.
    # WHY roll back an empty import: most providers import nothing; moving their generation on
    # every start would supersede flows in flight on other replicas and mint marker rows.
    # AIDEV-NOTE: the plugin writes through the app's Tortoise-backed stores, so its index and
    # blob writes commit or roll back with the claim (marker first).
    """
    provider = plugin.custom_llm_provider
    pair = await PairAuthorityStore().read(account_id, provider)
    if not fences_writer(pair):
        logger.info("bootstrap: skipping %s, its pair is owned by a Connection", provider)
        return
    try:
        async with in_transaction():
            await claim_pair(pair)
            before = await index_store.list(account_id, provider)
            await plugin.bootstrap_profiles(
                account_id=account_id,
                credential_store=credential_store,
                index_store=index_store,
            )
            if await index_store.list(account_id, provider) == before:
                raise _NothingImported
    except _NothingImported:
        return


__all__ = [
    "bootstrap_under_the_floor",
    "claim_observed",
    "claim_pair",
    "fences_writer",
    "hold_pair",
]
