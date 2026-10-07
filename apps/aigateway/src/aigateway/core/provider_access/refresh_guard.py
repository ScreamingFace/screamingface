"""G0 refresh guard: a refreshed token is published only by the owner that fetched it (OME-1497).

# FEATURE: OME-1138 D18, G0 part 2 (contract §5.3) — the four OAuth plugins fetch a refreshed token
# outside any transaction; this guard publishes it in one short transaction, only while the same
# owner still holds the blob it refreshed, and that blob is still the row and revision captured
# before the fetch.
# INVARIANT (owner decision 2026-10-07): the check is the blob's own row id and
# `credential_revision`, not the pair generation. Every writer that replaces, deletes or recreates
# this credential moves one of the two; an ownership change elsewhere on the pair does not, so it
# never burns a rotating refresh token. Refresh is not an ownership change: nothing here touches
# the pair marker.
# INVARIANT (lock order = the ownership writers' order, marker → owner → blob): this publication
# takes the owner row (a Connection row, or the account index for a Profile), then the blob row —
# a suffix of the writers' order, so it serializes with them and cannot deadlock against them.
# AIDEV-NOTE: a lost publication is `RefreshSuperseded`, never `AuthError` — callers answer the
# superseded conflict and mark nothing errored.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from tortoise.transactions import in_transaction

from ..credential_blob.model import CredentialBlob
from ..errors import RefreshSuperseded
from ..oauth.models import OAuthConnection
from ..oauth_base import BaseOAuthStrategy, RefreshPublication
from ..profile_index import ProfileIndexStore, ProfileTransitionConflict, lock_account_index


class _OwnerGone(Exception):
    """The owner the refresh was fetched for no longer holds its credential address."""


class _BlobMoved(Exception):
    """The blob the refresh was fetched from was rewritten, deleted or recreated meanwhile."""


@dataclass(frozen=True)
class BlobObservation:
    """The blob a refresh reads from, as captured before the provider round trip."""

    blob_id: UUID
    revision: int


async def _observe(service: str, account: str, *, lock: bool) -> BlobObservation | None:
    query = CredentialBlob.filter(service=service, account=account)
    # WHY a model-returning query: FOR UPDATE is dropped from `.values()` shapes in Tortoise.
    row = await (query.select_for_update() if lock else query).first()
    return None if row is None else BlobObservation(row.id, row.credential_revision)


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
    """`RefreshPublication` for one owner and its blob: publish only while both still stand."""

    def __init__(self, owner: RefreshOwner, *, service: str, account: str) -> None:
        self._owner = owner
        self._service = service
        self._account = account

    async def capture(self) -> BlobObservation | None:
        return await _observe(self._service, self._account, lock=False)

    async def publish(
        self, captured: object, write: Callable[[], Awaitable[None]]
    ) -> BlobObservation | None:
        if captured is not None and not isinstance(captured, BlobObservation):
            raise TypeError("a guarded refresh publishes only what its own capture observed")
        try:
            async with in_transaction():
                await self._owner.lock()
                current = await _observe(self._service, self._account, lock=True)
                # INVARIANT: an absent blob at capture means the credential was deleted under a
                # cached strategy — publishing would resurrect it.
                if captured is None or current != captured:
                    raise _BlobMoved
                await write()
                # INVARIANT (§5.3): tokens AND `last_refreshed_at` publish in this one
                # transaction, on the owner as committed now — never from a pre-fetch snapshot.
                await self._owner.stamp()
                # WHY read back under the row lock: the strategy keeps serving what it wrote, and
                # its next refresh must check exactly this revision.
                return await _observe(self._service, self._account, lock=False)
        except (_BlobMoved, _OwnerGone) as exc:
            # WHY caught outside the transaction: under PostgreSQL it is aborted by now.
            raise RefreshSuperseded(
                f"{self._owner.provider} refresh lost the credential it was fetched for"
            ) from exc


def guard_refresh(strategy: Any, owner: RefreshOwner) -> Any:
    """Bind the owner guard to an OAuth strategy the app built; any other strategy passes through.

    # AIDEV-NOTE: every app site that builds a strategy able to refresh binds it here (the §5.3
    # inventory: dispatch for a Profile and a Connection, the token service, the migrated facade,
    # the native and the legacy refresh routes). An unbound strategy writes directly.
    """
    if isinstance(strategy, BaseOAuthStrategy):
        publication: RefreshPublication = GuardedRefreshPublication(
            owner, service=strategy.credential_service(), account=strategy.credential_account()
        )
        strategy.bind_refresh_publication(publication)
    return strategy


__all__ = [
    "BlobObservation",
    "ConnectionRefreshOwner",
    "GuardedRefreshPublication",
    "ProfileRefreshOwner",
    "RefreshOwner",
    "guard_refresh",
]
