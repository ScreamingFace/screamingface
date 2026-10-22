from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from .auth_types import AuthType
from .credential_blob.model import CredentialBlob
from .credential_blob.store import CredentialBlobStore, ORMStore
from .profile_models import Profile, ProfileIndex, ProfileState

logger = logging.getLogger(__name__)

INDEX_CREDENTIAL_SERVICE = "aigateway:index"
LEGACY_INDEX_ACCOUNT = "default"
_INDEX_ACCOUNT_PREFIX = "account:"


class ProfileTransitionConflict(RuntimeError):
    """Raised when the document changed or vanished under a conditional write."""


def index_account_for(account_id: str) -> str:
    return f"{_INDEX_ACCOUNT_PREFIX}{account_id}"


async def lock_account_index(account_id: str) -> None:
    """Row-lock the account's index blob until the enclosing transaction ends; absent: no-op.

    # WHY (OME-1497, G0 §5.3): the account index is the serialization point every legacy Profile
    # writer passes before its credential blob, so a Profile-owned refresh publication that holds
    # it either commits before such a writer or sees what that writer committed.
    # AIDEV-NOTE: call inside `in_transaction()`; FOR UPDATE needs a model-returning query.
    """
    await (
        CredentialBlob.filter(
            service=INDEX_CREDENTIAL_SERVICE, account=index_account_for(account_id)
        )
        .select_for_update()
        .first()
    )


def _account_id_from_profile_id(profile_id: str) -> str:
    account_id, separator, _rest = profile_id.partition(":")
    if not separator or not account_id:
        raise ValueError("profile_id must include account_id")
    return account_id


class ProfileIndexStore:
    """Read/write account-scoped `aigateway:index` credential blobs."""

    def __init__(self, credential_store: CredentialBlobStore | None = None) -> None:
        self._store = credential_store or ORMStore()
        self._lock = asyncio.Lock()

    async def read(self, account_id: str | None = None) -> ProfileIndex:
        account = LEGACY_INDEX_ACCOUNT if account_id is None else index_account_for(account_id)
        raw = await self._store.read(INDEX_CREDENTIAL_SERVICE, account)
        if raw is None:
            if account_id is not None:
                return await self._read_legacy_account_index(account_id)
            return ProfileIndex()
        return ProfileIndex.model_validate_json(raw)

    async def _read_legacy_account_index(self, account_id: str) -> ProfileIndex:
        raw = await self._store.read(INDEX_CREDENTIAL_SERVICE, LEGACY_INDEX_ACCOUNT)
        if raw is None:
            return ProfileIndex()
        legacy = ProfileIndex.model_validate_json(raw)
        return ProfileIndex(profiles=[p for p in legacy.profiles if p.account_id == account_id])

    async def upsert(self, profile: Profile, *, require_present: bool = False) -> None:
        """Insert or replace ``profile`` in its account index row.

        INVARIANT: when ``require_present`` (the caller observed the profile as existing when
        its operation began), a concurrent delete that removed it WINS — publication raises
        ``ProfileTransitionConflict`` instead of silently resurrecting deleted state (OME-307
        Unit 3). The presence check runs INSIDE the mutator, so it is re-evaluated against the
        latest committed index on every ``ORMStore.mutate`` CAS retry; the index-row CAS is the
        sole cross-worker serializer. Default ``False`` keeps first-time API-key/OAuth creates
        and error-marking writes unconditional.
        """
        if not profile.account_id:
            raise ValueError("profile.account_id is required")

        async with self._lock:
            legacy_seed = await self._read_legacy_account_index(profile.account_id)

            def mutate(raw: str | None) -> str:
                # WHY: legacy installs used one global row; seed the account row lazily
                # so existing profiles survive the storage-shape split.
                idx = legacy_seed if raw is None else ProfileIndex.model_validate_json(raw)
                if require_present and not any(p.id == profile.id for p in idx.profiles):
                    raise ProfileTransitionConflict("profile was concurrently deleted")
                idx.profiles = [p for p in idx.profiles if p.id != profile.id] + [profile]
                return idx.model_dump_json()

            await self._store.mutate(
                INDEX_CREDENTIAL_SERVICE,
                index_account_for(profile.account_id),
                mutate,
            )

    async def stamp_refreshed(self, profile_id: str) -> Profile:
        """Mark the CURRENT entry refreshed now; the stamped entry, or `ProfileTransitionConflict`.

        # INVARIANT (OME-1497, G0 §5.3): only `state` and `last_refreshed_at` change, on the entry
        # as committed now — never a snapshot read before the provider round trip, which would
        # revert a key replacement or re-auth that committed meanwhile.
        # AIDEV-NOTE: deliberately WITHOUT the process `_lock`: the refresh guard calls this while
        # its transaction holds the index row, and a same-process upsert holding `_lock` may be
        # waiting on that row — taking `_lock` here would deadlock. The CAS stays the serializer.
        """
        account_id = _account_id_from_profile_id(profile_id)
        legacy_seed = await self._read_legacy_account_index(account_id)
        stamped: list[Profile] = []

        def mutate(raw: str | None) -> str:
            idx = legacy_seed if raw is None else ProfileIndex.model_validate_json(raw)
            current = next((p for p in idx.profiles if p.id == profile_id), None)
            if current is None:
                raise ProfileTransitionConflict("profile was concurrently deleted")
            # INVARIANT (§5.3): a re-auth started during the refresh window left the entry PENDING;
            # promoting it would turn that re-auth's callback into a false 409.
            state = (
                current.state
                if current.state == ProfileState.PENDING
                else ProfileState.AUTHENTICATED
            )
            updated = current.model_copy(
                update={"state": state, "last_refreshed_at": datetime.now(UTC)}
            )
            stamped[:] = [updated]
            idx.profiles = [p for p in idx.profiles if p.id != profile_id] + [updated]
            return idx.model_dump_json()

        await self._store.mutate(INDEX_CREDENTIAL_SERVICE, index_account_for(account_id), mutate)
        return stamped[0]

    async def mark_authenticated_error(
        self,
        profile_id: str,
        *,
        expected_auth_type: AuthType,
        expected_last_refreshed_at: datetime | None,
    ) -> None:
        """Mark ERROR only if the authenticated credential version still owns the profile."""
        account_id = _account_id_from_profile_id(profile_id)

        async with self._lock:
            legacy_seed = await self._read_legacy_account_index(account_id)

            def mutate(raw: str | None) -> str:
                idx = legacy_seed if raw is None else ProfileIndex.model_validate_json(raw)
                current = next((p for p in idx.profiles if p.id == profile_id), None)
                if (
                    current is None
                    or current.state is not ProfileState.AUTHENTICATED
                    or current.auth_type != expected_auth_type
                    or current.last_refreshed_at != expected_last_refreshed_at
                ):
                    raise ProfileTransitionConflict("profile credential owner changed")
                errored = current.model_copy(update={"state": ProfileState.ERROR})
                idx.profiles = [p for p in idx.profiles if p.id != profile_id] + [errored]
                return idx.model_dump_json()

            await self._store.mutate(
                INDEX_CREDENTIAL_SERVICE,
                index_account_for(account_id),
                mutate,
            )

    async def remove(self, profile_id: str) -> None:
        account_id = _account_id_from_profile_id(profile_id)

        async with self._lock:
            legacy_seed = await self._read_legacy_account_index(account_id)

            def mutate(raw: str | None) -> str:
                idx = legacy_seed if raw is None else ProfileIndex.model_validate_json(raw)
                idx.profiles = [p for p in idx.profiles if p.id != profile_id]
                return idx.model_dump_json()

            await self._store.mutate(
                INDEX_CREDENTIAL_SERVICE,
                index_account_for(account_id),
                mutate,
            )

    async def list(self, account_id: str, provider: str | None = None) -> list[Profile]:
        idx = await self.read(account_id)
        return [
            p
            for p in idx.profiles
            if p.account_id == account_id and (provider is None or p.provider == provider)
        ]

    async def get(self, account_id: str, provider: str, name: str) -> Profile | None:
        idx = await self.read(account_id)
        for p in idx.profiles:
            if p.account_id == account_id and p.provider == provider and p.name == name:
                return p
        return None
