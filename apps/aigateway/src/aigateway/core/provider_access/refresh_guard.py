"""G0 refresh guard: a refreshed token is published only by the owner that fetched it (OME-1497).

# FEATURE: OME-1138 D18, G0 part 2 (contract §5.3) — the four OAuth plugins fetch a refreshed token
# outside any transaction; this guard publishes it in one short transaction, only while the same
# owner still holds the pair at the generation captured before the fetch.
# INVARIANT: refresh is not an ownership change — the guard checks the generation and never
# advances it, so a browser re-auth in flight on the same row still completes at its captured
# generation.
# INVARIANT (lock order = the ownership writers' order, marker → owner → blob): a marked pair holds
# the marker row first; an unmarked pair has no row to lock, so the owner row is locked first and
# the marker must then still be absent. Ownership writers on the pair pass the same owner row (a
# Connection row, or the account index for a Profile) before their blob write, which serializes
# them against this publication.
# AIDEV-NOTE: a lost publication is `RefreshSuperseded`, never `AuthError` — callers answer the
# superseded conflict and mark nothing errored.
# AIDEV-NOTE (known risk, owner decision 2026-10-07): the check is pair-wide, as §5.3 states, so a
# generation move that does not touch this blob (another Connection created or started on the same
# provider during the ~1 s provider round trip) also makes the refresh lose. With a rotating
# refresh token the provider has already consumed the old one, so the next refresh of this owner
# may need a re-auth. Narrowing the check to the blob's own revision is the deferred fix.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from tortoise.transactions import in_transaction

from ..errors import RefreshSuperseded
from ..oauth.models import OAuthConnection
from ..oauth_base import BaseOAuthStrategy, RefreshPublication
from ..profile_index import ProfileIndexStore, ProfileTransitionConflict, lock_account_index
from .pair_authority import (
    UNMARKED_GENERATION,
    PairAuthority,
    PairAuthorityConflict,
    PairAuthorityStore,
)
from .writer_floor import hold_pair


class _OwnerGone(Exception):
    """The owner the refresh was fetched for no longer holds its credential address."""


@dataclass(frozen=True)
class ConnectionRefreshOwner:
    """A Connection row owns the refreshed blob (native row, or a migrated pair's effective row)."""

    account_id: str
    provider: str
    connection_id: UUID

    async def lock(self) -> None:
        # WHY a model-returning query: FOR UPDATE is dropped from `.values()` shapes in Tortoise.
        row = (
            await OAuthConnection.filter(id=self.connection_id, account_id=self.account_id)
            .select_for_update()
            .first()
        )
        if row is None or row.status == "revoked":
            raise _OwnerGone

    async def stamp(self) -> None:
        await OAuthConnection.filter(id=self.connection_id, account_id=self.account_id).update(
            last_refreshed_at=datetime.now(UTC)
        )


@dataclass(frozen=True)
class ProfileRefreshOwner:
    """A legacy Profile document owns the refreshed blob (a `none`/`quarantined` pair)."""

    account_id: str
    provider: str
    profile_id: str
    index: ProfileIndexStore

    async def lock(self) -> None:
        await lock_account_index(self.account_id)
        profiles = await self.index.list(self.account_id, self.provider)
        if not any(profile.id == self.profile_id for profile in profiles):
            raise _OwnerGone

    async def stamp(self) -> None:
        try:
            await self.index.stamp_refreshed(self.profile_id)
        except ProfileTransitionConflict as exc:
            raise _OwnerGone from exc


RefreshOwner = ConnectionRefreshOwner | ProfileRefreshOwner


class GuardedRefreshPublication:
    """`RefreshPublication` for one owner: capture the pair, publish only while it still stands."""

    def __init__(self, owner: RefreshOwner) -> None:
        self._owner = owner

    async def capture(self) -> PairAuthority:
        return await PairAuthorityStore().read(self._owner.account_id, self._owner.provider)

    async def publish(self, captured: object, write: Callable[[], Awaitable[None]]) -> None:
        if not isinstance(captured, PairAuthority):
            raise TypeError("a guarded refresh publishes only what its own capture observed")
        try:
            async with in_transaction():
                if captured.generation != UNMARKED_GENERATION:
                    await hold_pair(captured)
                    await self._owner.lock()
                else:
                    await self._owner.lock()
                    current = await PairAuthorityStore().read(
                        captured.account_id, captured.provider
                    )
                    if current.generation != UNMARKED_GENERATION:
                        raise PairAuthorityConflict(captured.provider, captured.generation)
                await write()
                # INVARIANT (§5.3): tokens AND `last_refreshed_at` publish in this one
                # transaction, on the owner as committed now — never from a pre-fetch snapshot.
                await self._owner.stamp()
        except (PairAuthorityConflict, _OwnerGone) as exc:
            # WHY caught outside the transaction: under PostgreSQL it is aborted by now.
            raise RefreshSuperseded(
                f"{captured.provider} refresh lost the pair it was fetched for"
            ) from exc


def guard_refresh(strategy: Any, owner: RefreshOwner) -> Any:
    """Bind the owner guard to an OAuth strategy the app built; any other strategy passes through.

    # AIDEV-NOTE: every app site that builds a strategy able to refresh binds it here (the §5.3
    # inventory: dispatch for a Profile and a Connection, the token service, the migrated facade,
    # the native and the legacy refresh routes). An unbound strategy writes directly.
    """
    if isinstance(strategy, BaseOAuthStrategy):
        publication: RefreshPublication = GuardedRefreshPublication(owner)
        strategy.bind_refresh_publication(publication)
    return strategy


__all__ = [
    "ConnectionRefreshOwner",
    "GuardedRefreshPublication",
    "ProfileRefreshOwner",
    "RefreshOwner",
    "guard_refresh",
]
