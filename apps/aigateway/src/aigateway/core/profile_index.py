"""The account-scoped profile index row: read, and mutate through its CAS.

The index row is the sole cross-worker serializer for profile ownership (OME-307):
every mutation below runs its decision INSIDE an ``ORMStore.mutate`` callback, so the
decision is re-evaluated against the latest committed row on each CAS retry.

WHY the ownership RULES live next door in :mod:`aigateway.core.profile_index_ownership`
and not here: they are pure predicates over an index document with no I/O, while this
store is already at the source-file size limit. The conflict types are re-exported here
(PEP 484 redundant alias) because callers import them from this module.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from .credential_blob.store import CredentialBlobStore, ORMStore
from .profile_index_ownership import (
    CredentialOwnershipConflict as CredentialOwnershipConflict,
)
from .profile_index_ownership import (
    ProfileTransitionConflict as ProfileTransitionConflict,
)
from .profile_index_ownership import (
    bump_credential_generation,
    require_expected_ownership,
)
from .profile_models import AuthType, Profile, ProfileDefaults, ProfileIndex, ProfileState

logger = logging.getLogger(__name__)

INDEX_CREDENTIAL_SERVICE = "aigateway:index"
_LEGACY_INDEX_ACCOUNT = "default"
_INDEX_ACCOUNT_PREFIX = "account:"


def _index_account_for(account_id: str) -> str:
    return f"{_INDEX_ACCOUNT_PREFIX}{account_id}"


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
        account = _LEGACY_INDEX_ACCOUNT if account_id is None else _index_account_for(account_id)
        raw = await self._store.read(INDEX_CREDENTIAL_SERVICE, account)
        if raw is None:
            if account_id is not None:
                return await self._read_legacy_account_index(account_id)
            return ProfileIndex()
        return ProfileIndex.model_validate_json(raw)

    async def _read_legacy_account_index(self, account_id: str) -> ProfileIndex:
        raw = await self._store.read(INDEX_CREDENTIAL_SERVICE, _LEGACY_INDEX_ACCOUNT)
        if raw is None:
            return ProfileIndex()
        legacy = ProfileIndex.model_validate_json(raw)
        return ProfileIndex(profiles=[p for p in legacy.profiles if p.account_id == account_id])

    async def upsert(
        self,
        profile: Profile,
        *,
        require_present: bool = False,
        credential_owner_unchanged: bool = False,
        expected_credential_generation: int | None = None,
        expected_auth_type: AuthType | None = None,
    ) -> None:
        """Insert or replace ``profile`` in its account index row.

        ``credential_owner_unchanged`` suppresses the credential-generation bump for a
        write that does NOT replace the credential's owner — today only a routine token
        refresh (see :func:`_bump_credential_generation` for the contract).

        # WHY it defaults to ``False``, i.e. to bumping: the two mistakes are not
        # symmetric. Bumping when nothing changed costs one avoidable catalog refetch;
        # NOT bumping when the owner changed lets one owner's cached private catalog be
        # served under another's credential. A new call site that forgets to think about
        # this gets the safe answer.

        INVARIANT: when ``require_present`` (the caller observed the profile as existing when
        its operation began), a concurrent delete that removed it WINS — publication raises
        ``ProfileTransitionConflict`` instead of silently resurrecting deleted state (OME-307
        Unit 3). The presence check runs INSIDE the mutator, so it is re-evaluated against the
        latest committed index on every ``ORMStore.mutate`` CAS retry; the index-row CAS is the
        sole cross-worker serializer. Default ``False`` keeps first-time API-key/OAuth creates
        and error-marking writes unconditional.

        INVARIANT (OME-1026 adversarial B2): ``expected_credential_generation`` and
        ``expected_auth_type`` make publication conditional on OWNERSHIP, not merely on
        presence. ``require_present`` alone is satisfied by a profile a DIFFERENT owner now
        holds — which is how a stale refresh restored the previous owner's metadata over a
        committed replacement while the durable generation stayed the replacement's. Both
        checks run inside the same mutator as the presence check, so they are re-evaluated on
        every CAS retry and are safe across workers. Raises
        :class:`CredentialOwnershipConflict` (a ``ProfileTransitionConflict``, so existing
        handlers keep working) when either no longer matches.
        """
        if not profile.account_id:
            raise ValueError("profile.account_id is required")

        async with self._lock:
            legacy_seed = await self._read_legacy_account_index(profile.account_id)

            def mutate(raw: str | None) -> str:
                # WHY: legacy installs used one global row; seed the account row lazily
                # so existing profiles survive the storage-shape split.
                idx = legacy_seed if raw is None else ProfileIndex.model_validate_json(raw)
                current = next((p for p in idx.profiles if p.id == profile.id), None)
                if require_present and current is None:
                    raise ProfileTransitionConflict("profile was concurrently deleted")
                require_expected_ownership(
                    idx,
                    current,
                    profile_id=profile.id,
                    expected_generation=expected_credential_generation,
                    expected_auth_type=expected_auth_type,
                )
                if not credential_owner_unchanged:
                    bump_credential_generation(idx, profile.id)
                idx.profiles = [p for p in idx.profiles if p.id != profile.id] + [profile]
                return idx.model_dump_json()

            await self._store.mutate(
                INDEX_CREDENTIAL_SERVICE,
                _index_account_for(profile.account_id),
                mutate,
            )

    async def begin_pending(self, profile: Profile) -> int:
        """Publish ``profile`` as pending and claim a fresh ownership generation.

        Returns the generation assigned to THIS operation. INVARIANT (OME-307 Blocker 1):
        the profile row and its ownership generation are written in ONE atomic index-row CAS,
        so a later ``begin_pending`` for the same profile strictly supersedes this one. The
        generation the caller receives is the token it must later present to
        ``authenticate_pending``; a stale caller whose generation was bumped loses even though
        the row is still PENDING. The generation is an internal nonce — never surfaced via API.
        """
        if not profile.account_id:
            raise ValueError("profile.account_id is required")

        assigned: dict[str, int] = {}
        async with self._lock:
            legacy_seed = await self._read_legacy_account_index(profile.account_id)

            def mutate(raw: str | None) -> str:
                idx = legacy_seed if raw is None else ProfileIndex.model_validate_json(raw)
                generation = idx.oauth_generations.get(profile.id, 0) + 1
                idx.oauth_generations[profile.id] = generation
                idx.profiles = [p for p in idx.profiles if p.id != profile.id] + [profile]
                # On a CAS retry mutate() re-runs against the latest committed row, so the
                # last (successful) run's generation is the one that is durably stored.
                assigned["generation"] = generation
                return idx.model_dump_json()

            await self._store.mutate(
                INDEX_CREDENTIAL_SERVICE,
                _index_account_for(profile.account_id),
                mutate,
            )
        return assigned["generation"]

    async def authenticate_pending(
        self,
        profile: Profile,
        *,
        expected_generation: int | None = None,
        account_label: str | None = None,
    ) -> None:
        """Atomically replace a still-pending profile with its authenticated form.

        INVARIANT: exactly ONE conditional durable publication under a SINGLE process-
        lock acquisition. The optimistic CAS below (guarded on the current ciphertext by
        ``ORMStore.mutate``) is the sole cross-worker serializer; the process ``_lock`` is
        only a same-process convenience. The lock is released before the caller's
        enclosing transaction commits and is never re-acquired afterwards, so a second
        writer can never invert the application-lock / index-row-lock order (OME-307
        Unit 1 — a trailing ``upsert`` here previously deadlocked concurrent OAuth
        callbacks on PostgreSQL).

        INVARIANT (OME-307 Blocker 1): when ``expected_generation`` is supplied, OWNERSHIP is
        enforced INSIDE this same atomic CAS — not by a separate in-memory precheck. A stale
        flow whose generation was superseded by a newer ``begin_pending`` loses here even
        though the row is still PENDING, closing the check-then-act TOCTOU window. The
        ``state is PENDING`` guard remains as defense in depth for the case where a newer flow
        (or an API-key write) has already committed a non-pending state.
        """
        if not profile.account_id:
            raise ValueError("profile.account_id is required")

        async with self._lock:
            legacy_seed = await self._read_legacy_account_index(profile.account_id)

            def mutate(raw: str | None) -> str:
                idx = legacy_seed if raw is None else ProfileIndex.model_validate_json(raw)
                current = next((item for item in idx.profiles if item.id == profile.id), None)
                # INVARIANT: a consumed OAuth callback cannot overwrite a later API-key choice.
                if current is None or current.state is not ProfileState.PENDING:
                    raise ProfileTransitionConflict("profile is no longer pending")
                if (
                    expected_generation is not None
                    and idx.oauth_generations.get(profile.id) != expected_generation
                ):
                    raise ProfileTransitionConflict("a newer OAuth flow owns this pending profile")
                changes = {
                    "state": profile.state,
                    "auth_type": profile.auth_type,
                    # WHY (OME-307 M-1): publish last_refreshed_at inside this SAME CAS so it
                    # joins mark_authenticated_error's ownership fence. Omitting it left the row
                    # at the pending None, letting a stale refresh-failure carrying that None
                    # error the freshly re-authenticated owner.
                    "last_refreshed_at": profile.last_refreshed_at,
                }
                if account_label is not None:
                    changes["account_label"] = account_label
                bump_credential_generation(idx, profile.id)
                published = current.model_copy(update=changes)
                # INVARIANT: merge lifecycle fields into the row validated by this CAS. A
                # metadata PATCH that committed after the callback's earlier read must survive.
                idx.profiles = [item for item in idx.profiles if item.id != profile.id] + [
                    published
                ]
                return idx.model_dump_json()

            await self._store.mutate(
                INDEX_CREDENTIAL_SERVICE,
                _index_account_for(profile.account_id),
                mutate,
            )

    async def mark_pending_error(self, profile_id: str, *, expected_generation: int) -> None:
        """Transition a still-owned pending profile to ERROR under ONE atomic index CAS.

        INVARIANT (OME-307 Blocker 2): mark ERROR only if the profile is still present, still
        PENDING, and still owned by ``expected_generation``. A newer OAuth flow, a committed
        API-key write, or a delete means this failed operation no longer owns the row, so the
        stale failure raises ``ProfileTransitionConflict`` (the caller treats it as "not mine,
        nothing to mark") rather than corrupting the newer state. The presence check is
        require_present — a deleted profile is NEVER recreated. All three conditions are checked
        inside the mutator so they re-evaluate on every ``ORMStore.mutate`` CAS retry.
        """
        account_id = _account_id_from_profile_id(profile_id)

        async with self._lock:
            legacy_seed = await self._read_legacy_account_index(account_id)

            def mutate(raw: str | None) -> str:
                idx = legacy_seed if raw is None else ProfileIndex.model_validate_json(raw)
                current = next((p for p in idx.profiles if p.id == profile_id), None)
                if current is None or current.state is not ProfileState.PENDING:
                    raise ProfileTransitionConflict(
                        "profile is not a pending profile this operation owns"
                    )
                if idx.oauth_generations.get(profile_id) != expected_generation:
                    raise ProfileTransitionConflict("a newer OAuth flow owns this pending profile")
                errored = current.model_copy(update={"state": ProfileState.ERROR})
                idx.profiles = [p for p in idx.profiles if p.id != profile_id] + [errored]
                return idx.model_dump_json()

            await self._store.mutate(
                INDEX_CREDENTIAL_SERVICE,
                _index_account_for(account_id),
                mutate,
            )

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
                _index_account_for(account_id),
                mutate,
            )

    async def update_metadata(
        self,
        profile_id: str,
        *,
        defaults: ProfileDefaults | None = None,
        account_label: str | None = None,
    ) -> Profile:
        """Patch non-lifecycle fields against the latest present profile atomically."""
        account_id = _account_id_from_profile_id(profile_id)
        updated: dict[str, Profile] = {}

        async with self._lock:
            legacy_seed = await self._read_legacy_account_index(account_id)

            def mutate(raw: str | None) -> str:
                idx = legacy_seed if raw is None else ProfileIndex.model_validate_json(raw)
                current = next((p for p in idx.profiles if p.id == profile_id), None)
                if current is None:
                    raise ProfileTransitionConflict("profile was concurrently deleted")
                changes = {}
                if defaults is not None:
                    changes["defaults"] = defaults
                if account_label is not None:
                    changes["account_label"] = account_label
                patched = current.model_copy(update=changes)
                idx.profiles = [p for p in idx.profiles if p.id != profile_id] + [patched]
                updated["profile"] = patched
                return idx.model_dump_json()

            await self._store.mutate(
                INDEX_CREDENTIAL_SERVICE,
                _index_account_for(account_id),
                mutate,
            )
        return updated["profile"]

    async def remove(self, profile_id: str) -> None:
        account_id = _account_id_from_profile_id(profile_id)

        async with self._lock:
            legacy_seed = await self._read_legacy_account_index(account_id)

            def mutate(raw: str | None) -> str:
                idx = legacy_seed if raw is None else ProfileIndex.model_validate_json(raw)
                idx.profiles = [p for p in idx.profiles if p.id != profile_id]
                # INVARIANT: retain the last generation as an internal tombstone. Reusing an old
                # number after delete/recreate would let a callback consumed before the delete
                # authenticate the new pending profile. Presence/state checks still prevent a
                # deleted profile from being authenticated or marked ERROR.
                return idx.model_dump_json()

            await self._store.mutate(
                INDEX_CREDENTIAL_SERVICE,
                _index_account_for(account_id),
                mutate,
            )

    async def list(self, account_id: str, provider: str | None = None) -> list[Profile]:
        idx = await self.read(account_id)
        return [
            p
            for p in idx.profiles
            if p.account_id == account_id and (provider is None or p.provider == provider)
        ]

    async def get_with_credential_generation(
        self, account_id: str, provider: str, name: str
    ) -> tuple[Profile, int] | None:
        """The profile AND its durable credential generation, from ONE index read.

        # WHY combined rather than a second lookup (OME-1026 F3): reading the index
        # decrypts a credential blob. The private model catalog needs both values on
        # every request, and splitting them would double that decryption per request.
        """
        idx = await self.read(account_id)
        for p in idx.profiles:
            if p.account_id == account_id and p.provider == provider and p.name == name:
                return p, idx.credential_generations.get(p.id, 0)
        return None

    async def get(self, account_id: str, provider: str, name: str) -> Profile | None:
        idx = await self.read(account_id)
        for p in idx.profiles:
            if p.account_id == account_id and p.provider == provider and p.name == name:
                return p
        return None
