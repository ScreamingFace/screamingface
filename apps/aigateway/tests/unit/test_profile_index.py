from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from tortoise import Tortoise

import aigateway.core.credential_blob.store as credential_blob_store
from aigateway.core.credential_blob.model import CredentialBlob
from aigateway.core.credential_blob.store import CredentialBlobMutationConflict, ORMStore
from aigateway.core.profile_index import (
    INDEX_CREDENTIAL_SERVICE,
    ProfileIndexStore,
    ProfileTransitionConflict,
)
from aigateway.core.profile_models import (
    Profile,
    ProfileDefaults,
    ProfileIndex,
    ProfileState,
    profile_id_for,
)
from aigateway.core.secrets.local import LocalSecretStore
from aigateway.core.secrets.mixin import SecretStoreMixin
from aigateway.db import build_tortoise_config

ACCOUNT_ID = "account-1"
OTHER_ACCOUNT_ID = "account-2"
_TEST_KEY = bytes(range(32))


def _index_account(account_id: str) -> str:
    return f"account:{account_id}"


class _BarrierSecretStore(SecretStoreMixin):
    """Hold concurrent writes until both read the old profile index."""

    def __init__(self, release_after_encrypts: int) -> None:
        self._inner = LocalSecretStore(_TEST_KEY)
        self._release_after_encrypts = release_after_encrypts
        self._release = asyncio.Event()
        self.encrypt_calls = 0

    @property
    def version(self) -> str:
        return self._inner.version

    async def encrypt(self, value: str) -> str:
        self.encrypt_calls += 1
        if self.encrypt_calls >= self._release_after_encrypts:
            self._release.set()
        await self._release.wait()
        return await self._inner.encrypt(value)

    async def decrypt(self, value: str) -> str:
        return await self._inner.decrypt(value)


@pytest_asyncio.fixture
async def orm_profile_stores(credential_blobs):
    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{credential_blobs.db_path}"),
        _enable_global_fallback=True,
    )
    secret_store = _BarrierSecretStore(release_after_encrypts=2)
    try:
        yield (
            ProfileIndexStore(credential_store=ORMStore(secret_store=secret_store)),
            ProfileIndexStore(credential_store=ORMStore(secret_store=secret_store)),
            secret_store,
        )
    finally:
        await Tortoise.close_connections()


@pytest_asyncio.fixture
async def plain_orm_profile_stores(credential_blobs):
    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{credential_blobs.db_path}"),
        _enable_global_fallback=True,
    )
    secret_store = LocalSecretStore(_TEST_KEY)
    try:
        yield (
            ProfileIndexStore(credential_store=ORMStore(secret_store=secret_store)),
            ProfileIndexStore(credential_store=ORMStore(secret_store=secret_store)),
        )
    finally:
        await Tortoise.close_connections()


def test_profile_round_trips_through_json() -> None:
    p = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "default"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="default",
        account_label="user@example.com",
        scopes=["user:inference"],
        last_refreshed_at=None,
        state=ProfileState.AUTHENTICATED,
        defaults=ProfileDefaults(model="anthropic/claude-sonnet-4-5", max_tokens=4096),
    )
    raw = p.model_dump_json()
    restored = Profile.model_validate_json(raw)
    assert restored == p


def test_profile_index_serializes_with_version() -> None:
    idx = ProfileIndex(version=1, profiles=[])
    data = idx.model_dump()
    # oauth_generations carries the per-profile OAuth ownership nonces (OME-307 Blocker 1);
    # it defaults to an empty map and is part of the durable index document.
    # credential_generations (OME-1026 F3, owner-approved re-pin) joined it for the same
    # reason and by the same rule: a per-profile counter bumped inside the index CAS, so
    # it is durable index state and MUST appear here. The two are deliberately separate —
    # overloading the OAuth nonce would make a credential change look like a superseded
    # OAuth flow and break authenticate_pending's ownership check.
    assert data == {
        "version": 1,
        "profiles": [],
        "oauth_generations": {},
        "credential_generations": {},
    }


@pytest.mark.asyncio
async def test_index_store_returns_empty_index_when_store_empty(credential_blobs) -> None:
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    idx = await store.read(ACCOUNT_ID)
    assert idx.version == 1
    assert idx.profiles == []


@pytest.mark.asyncio
async def test_index_store_round_trip(credential_blobs) -> None:
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    p = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "default"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="default",
        defaults=ProfileDefaults(model="anthropic/claude-sonnet-4-5"),
    )
    await store.upsert(p)
    idx = await store.read(ACCOUNT_ID)
    assert len(idx.profiles) == 1
    assert idx.profiles[0].id == profile_id_for(ACCOUNT_ID, "anthropic", "default")
    assert idx.profiles[0].account_id == ACCOUNT_ID
    raw = credential_blobs.read(INDEX_CREDENTIAL_SERVICE, _index_account(ACCOUNT_ID))
    assert profile_id_for(ACCOUNT_ID, "anthropic", "default") in raw
    assert credential_blobs.read(INDEX_CREDENTIAL_SERVICE, "default") is None


@pytest.mark.asyncio
async def test_index_store_upsert_replaces_by_id(credential_blobs) -> None:
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    await store.upsert(
        Profile(
            id=profile_id_for(ACCOUNT_ID, "anthropic", "default"),
            account_id=ACCOUNT_ID,
            provider="anthropic",
            name="default",
        )
    )
    await store.upsert(
        Profile(
            id=profile_id_for(ACCOUNT_ID, "anthropic", "default"),
            account_id=ACCOUNT_ID,
            provider="anthropic",
            name="default",
            account_label="updated@example.com",
        )
    )
    idx = await store.read(ACCOUNT_ID)
    assert len(idx.profiles) == 1
    assert idx.profiles[0].account_label == "updated@example.com"


@pytest.mark.asyncio
async def test_index_store_remove(credential_blobs) -> None:
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    await store.upsert(
        Profile(
            id=profile_id_for(ACCOUNT_ID, "anthropic", "default"),
            account_id=ACCOUNT_ID,
            provider="anthropic",
            name="default",
        )
    )
    await store.remove(profile_id_for(ACCOUNT_ID, "anthropic", "default"))
    idx = await store.read(ACCOUNT_ID)
    assert idx.profiles == []


@pytest.mark.asyncio
async def test_index_store_lazy_reads_legacy_default_row(credential_blobs) -> None:
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    legacy = ProfileIndex(
        profiles=[
            Profile(
                id=profile_id_for(ACCOUNT_ID, "anthropic", "default"),
                account_id=ACCOUNT_ID,
                provider="anthropic",
                name="default",
            ),
            Profile(
                id=profile_id_for(OTHER_ACCOUNT_ID, "gemini", "work"),
                account_id=OTHER_ACCOUNT_ID,
                provider="gemini",
                name="work",
            ),
        ]
    )
    credential_blobs.write(INDEX_CREDENTIAL_SERVICE, "default", legacy.model_dump_json())

    profiles = await store.list(ACCOUNT_ID)

    assert [p.name for p in profiles] == ["default"]
    assert await store.get(OTHER_ACCOUNT_ID, "gemini", "work") is not None


@pytest.mark.asyncio
async def test_index_store_seeds_account_row_from_legacy_default_row(credential_blobs) -> None:
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    legacy_profile = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "legacy"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="legacy",
    )
    other_account_profile = Profile(
        id=profile_id_for(OTHER_ACCOUNT_ID, "anthropic", "other"),
        account_id=OTHER_ACCOUNT_ID,
        provider="anthropic",
        name="other",
    )
    credential_blobs.write(
        INDEX_CREDENTIAL_SERVICE,
        "default",
        ProfileIndex(profiles=[legacy_profile, other_account_profile]).model_dump_json(),
    )

    await store.upsert(
        Profile(
            id=profile_id_for(ACCOUNT_ID, "anthropic", "new"),
            account_id=ACCOUNT_ID,
            provider="anthropic",
            name="new",
        )
    )

    profiles = await store.list(ACCOUNT_ID)
    assert {p.name for p in profiles} == {"legacy", "new"}
    raw = credential_blobs.read(INDEX_CREDENTIAL_SERVICE, _index_account(ACCOUNT_ID))
    assert raw is not None
    assert profile_id_for(ACCOUNT_ID, "anthropic", "legacy") in raw
    assert profile_id_for(ACCOUNT_ID, "anthropic", "new") in raw
    assert profile_id_for(OTHER_ACCOUNT_ID, "anthropic", "other") not in raw


@pytest.mark.asyncio
async def test_index_store_remove_seeds_account_row_from_legacy_default_row(
    credential_blobs,
) -> None:
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    remove_profile = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "remove"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="remove",
    )
    keep_profile = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "keep"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="keep",
    )
    credential_blobs.write(
        INDEX_CREDENTIAL_SERVICE,
        "default",
        ProfileIndex(profiles=[remove_profile, keep_profile]).model_dump_json(),
    )

    await store.remove(remove_profile.id)

    profiles = await store.list(ACCOUNT_ID)
    assert [p.name for p in profiles] == ["keep"]


@pytest.mark.asyncio
async def test_index_store_filters_by_account(credential_blobs) -> None:
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    await store.upsert(
        Profile(
            id=profile_id_for(ACCOUNT_ID, "anthropic", "default"),
            account_id=ACCOUNT_ID,
            provider="anthropic",
            name="default",
        )
    )
    await store.upsert(
        Profile(
            id=profile_id_for(OTHER_ACCOUNT_ID, "anthropic", "default"),
            account_id=OTHER_ACCOUNT_ID,
            provider="anthropic",
            name="default",
        )
    )

    profiles = await store.list(ACCOUNT_ID)
    assert len(profiles) == 1
    assert profiles[0].account_id == ACCOUNT_ID
    assert await store.get(OTHER_ACCOUNT_ID, "anthropic", "default") is not None
    assert await store.get(ACCOUNT_ID, "anthropic", "missing") is None


@pytest.mark.asyncio
async def test_concurrent_upserts_preserve_both_profiles() -> None:
    """The per-store asyncio.Lock must serialize read-modify-write cycles so
    concurrent writers (e.g. chat error-marking racing a PUT api-key) cannot
    drop each other's profiles (SF-244 audit F25)."""
    import asyncio

    class _YieldingStore:
        def __init__(self) -> None:
            self.data: dict[tuple[str, str], str] = {}

        async def read(self, service: str, account: str) -> str | None:
            await asyncio.sleep(0)  # force interleaving between read and write
            return self.data.get((service, account))

        async def write(self, service: str, account: str, value: str) -> None:
            await asyncio.sleep(0)
            self.data[(service, account)] = value

        async def delete(self, service: str, account: str) -> None:
            self.data.pop((service, account), None)

        async def mutate(self, service: str, account: str, mutator) -> None:
            await asyncio.sleep(0)
            next_value = mutator(self.data.get((service, account)))
            if next_value is None:
                self.data.pop((service, account), None)
            else:
                self.data[(service, account)] = next_value

    store = ProfileIndexStore(credential_store=_YieldingStore())
    first = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "one"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="one",
    )
    second = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "two"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="two",
        auth_type="api_key",
    )

    await asyncio.gather(store.upsert(first), store.upsert(second))

    profiles = await store.list(ACCOUNT_ID)
    assert {p.name for p in profiles} == {"one", "two"}
    assert {p.auth_type for p in profiles} == {"oauth", "api_key"}


@pytest.mark.asyncio
async def test_isolated_orm_stores_retry_empty_index_create_race(orm_profile_stores) -> None:
    """Separate gateway workers must not lose the first concurrent profile writes."""
    first_store, second_store, secret_store = orm_profile_stores
    first = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "one"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="one",
    )
    second = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "two"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="two",
        auth_type="api_key",
    )

    await asyncio.gather(first_store.upsert(first), second_store.upsert(second))

    profiles = await first_store.list(ACCOUNT_ID)
    assert {p.name for p in profiles} == {"one", "two"}
    assert secret_store.encrypt_calls >= 3  # two initial attempts plus the CAS retry


@pytest.mark.asyncio
async def test_isolated_orm_stores_do_not_contend_across_accounts(
    plain_orm_profile_stores,
    credential_blobs,
) -> None:
    first_store, second_store = plain_orm_profile_stores
    first = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "one"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="one",
    )
    second = Profile(
        id=profile_id_for(OTHER_ACCOUNT_ID, "anthropic", "two"),
        account_id=OTHER_ACCOUNT_ID,
        provider="anthropic",
        name="two",
    )

    await asyncio.gather(first_store.upsert(first), second_store.upsert(second))

    assert await first_store.get(ACCOUNT_ID, "anthropic", "one") is not None
    assert await first_store.get(OTHER_ACCOUNT_ID, "anthropic", "two") is not None
    assert (
        credential_blobs.read_raw(INDEX_CREDENTIAL_SERVICE, _index_account(ACCOUNT_ID)) is not None
    )
    assert (
        credential_blobs.read_raw(INDEX_CREDENTIAL_SERVICE, _index_account(OTHER_ACCOUNT_ID))
        is not None
    )
    assert credential_blobs.read_raw(INDEX_CREDENTIAL_SERVICE, "default") is None


@pytest.mark.asyncio
async def test_profile_index_mutation_conflict_exhaustion_is_loud(
    credential_blobs, monkeypatch
) -> None:
    class _ConflictOnceSecretStore(SecretStoreMixin):
        def __init__(self) -> None:
            self._inner = LocalSecretStore(_TEST_KEY)
            self.conflicted = False

        @property
        def version(self) -> str:
            return self._inner.version

        async def encrypt(self, value: str) -> str:
            return await self._inner.encrypt(value)

        async def decrypt(self, value: str) -> str:
            plaintext = await self._inner.decrypt(value)
            if not self.conflicted:
                self.conflicted = True
                replacement = await self._inner.encrypt(ProfileIndex().model_dump_json())
                await CredentialBlob.filter(
                    service=INDEX_CREDENTIAL_SERVICE,
                    account=_index_account(ACCOUNT_ID),
                ).update(value=replacement, ciphertext_version=self.version)
            return plaintext

    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{credential_blobs.db_path}"),
        _enable_global_fallback=True,
    )
    monkeypatch.setattr(credential_blob_store, "_MUTATE_MAX_ATTEMPTS", 1)
    try:
        seed_store = ProfileIndexStore(
            credential_store=ORMStore(secret_store=LocalSecretStore(_TEST_KEY))
        )
        await seed_store.upsert(
            Profile(
                id=profile_id_for(ACCOUNT_ID, "anthropic", "seed"),
                account_id=ACCOUNT_ID,
                provider="anthropic",
                name="seed",
            )
        )
        conflict_store = ProfileIndexStore(
            credential_store=ORMStore(secret_store=_ConflictOnceSecretStore())
        )

        with pytest.raises(CredentialBlobMutationConflict):
            await conflict_store.upsert(
                Profile(
                    id=profile_id_for(ACCOUNT_ID, "anthropic", "new"),
                    account_id=ACCOUNT_ID,
                    provider="anthropic",
                    name="new",
                )
            )
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_profile_index_mutation_exhaustion_does_not_sleep_after_final_attempt(
    credential_blobs, monkeypatch
) -> None:
    class _AlwaysConflictSecretStore(SecretStoreMixin):
        def __init__(self) -> None:
            self._inner = LocalSecretStore(_TEST_KEY)

        @property
        def version(self) -> str:
            return self._inner.version

        async def encrypt(self, value: str) -> str:
            return await self._inner.encrypt(value)

        async def decrypt(self, value: str) -> str:
            replacement = await self._inner.encrypt(ProfileIndex().model_dump_json())
            await CredentialBlob.filter(
                service=INDEX_CREDENTIAL_SERVICE,
                account=_index_account(ACCOUNT_ID),
            ).update(value=replacement, ciphertext_version=self.version)
            return await self._inner.decrypt(value)

    sleep_attempts: list[int] = []

    async def _record_sleep(attempt: int) -> None:
        sleep_attempts.append(attempt)

    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{credential_blobs.db_path}"),
        _enable_global_fallback=True,
    )
    monkeypatch.setattr(credential_blob_store, "_MUTATE_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(credential_blob_store, "_sleep_before_mutation_retry", _record_sleep)
    try:
        seed_store = ProfileIndexStore(
            credential_store=ORMStore(secret_store=LocalSecretStore(_TEST_KEY))
        )
        await seed_store.upsert(
            Profile(
                id=profile_id_for(ACCOUNT_ID, "anthropic", "seed"),
                account_id=ACCOUNT_ID,
                provider="anthropic",
                name="seed",
            )
        )
        conflict_store = ProfileIndexStore(
            credential_store=ORMStore(secret_store=_AlwaysConflictSecretStore())
        )

        with pytest.raises(CredentialBlobMutationConflict):
            await conflict_store.upsert(
                Profile(
                    id=profile_id_for(ACCOUNT_ID, "anthropic", "new"),
                    account_id=ACCOUNT_ID,
                    provider="anthropic",
                    name="new",
                )
            )

        assert sleep_attempts == []
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_isolated_orm_stores_preserve_concurrent_remove_and_upsert(
    plain_orm_profile_stores,
) -> None:
    seed_store, _ = plain_orm_profile_stores
    keep = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "keep"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="keep",
    )
    remove = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "remove"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="remove",
    )
    await seed_store.upsert(keep)
    await seed_store.upsert(remove)

    barrier = _BarrierSecretStore(release_after_encrypts=2)
    first_store = ProfileIndexStore(credential_store=ORMStore(secret_store=barrier))
    second_store = ProfileIndexStore(credential_store=ORMStore(secret_store=barrier))
    add = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "add"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="add",
    )

    await asyncio.gather(first_store.remove(remove.id), second_store.upsert(add))

    profiles = await seed_store.list(ACCOUNT_ID)
    assert {p.name for p in profiles} == {"keep", "add"}
    assert barrier.encrypt_calls >= 3


@pytest.mark.asyncio
async def test_authenticate_pending_rejects_superseded_generation(credential_blobs) -> None:
    """OME-307 Blocker 1 — ownership lives INSIDE the durable publication CAS.

    FEATURE: profile OAuth authentication with concurrent-flow safety.
    STORY: as a user who restarts an OAuth login for a profile while an earlier attempt is
    still exchanging its code, the earlier (stale) attempt must not hijack the profile the
    new attempt now owns.

    INVARIANT: a stale OAuth flow whose ownership generation was superseded by a newer
    ``start_oauth`` for the same profile LOSES its publication even though the durable row is
    still PENDING. A generic ``state == pending`` CAS cannot see the newer owner; binding a
    per-operation generation into the SAME atomic CAS makes the stale flow fail with
    ``ProfileTransitionConflict`` while the newer owner keeps the pending profile and can still
    complete. The generation is an operation nonce and never leaves the index document, so it
    is never exposed through the profile API.
    """
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    pending = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "work"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="work",
        state=ProfileState.PENDING,
    )

    generation_a = await store.begin_pending(pending)
    generation_b = await store.begin_pending(pending)  # a newer start_oauth supersedes flow A
    assert generation_b != generation_a

    authenticated = pending.model_copy(update={"state": ProfileState.AUTHENTICATED})

    # Flow A publishes with its now-stale generation: it must lose even though state==PENDING.
    with pytest.raises(ProfileTransitionConflict):
        await store.authenticate_pending(authenticated, expected_generation=generation_a)
    still_pending = await store.get(ACCOUNT_ID, "anthropic", "work")
    assert still_pending is not None
    assert still_pending.state is ProfileState.PENDING  # A wrote nothing

    # Flow B — the current owner — publishes with its generation and wins.
    await store.authenticate_pending(authenticated, expected_generation=generation_b)
    published = await store.get(ACCOUNT_ID, "anthropic", "work")
    assert published is not None
    assert published.state is ProfileState.AUTHENTICATED


@pytest.mark.asyncio
async def test_mark_pending_error_only_marks_still_owned_pending_profile(credential_blobs) -> None:
    """OME-307 Blocker 2 — a stale OAuth failure must not corrupt a newer owner.

    FEATURE: profile OAuth authentication with concurrent-flow safety.
    INVARIANT: ``mark_pending_error`` transitions PENDING->ERROR only if the profile is still
    present, still PENDING, and still owned by the failing operation's generation. Three stale
    schedules must each be rejected with ``ProfileTransitionConflict`` and leave the newer
    state intact: a newer OAuth flow, a committed API-key profile, and a deleted profile (which
    must never be resurrected).
    """
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    profile_id = profile_id_for(ACCOUNT_ID, "anthropic", "work")
    pending = Profile(
        id=profile_id,
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="work",
        state=ProfileState.PENDING,
    )

    # Schedule 1 — a newer OAuth flow (B) supersedes A before A's failure fires.
    generation_a = await store.begin_pending(pending)
    await store.begin_pending(pending)  # flow B claims a newer generation
    with pytest.raises(ProfileTransitionConflict):
        await store.mark_pending_error(profile_id, expected_generation=generation_a)
    survivor = await store.get(ACCOUNT_ID, "anthropic", "work")
    assert survivor is not None
    assert survivor.state is ProfileState.PENDING  # B's pending profile untouched

    # Schedule 2 — a committed API-key profile replaced the pending flow before A failed.
    generation_a2 = await store.begin_pending(pending)
    await store.upsert(
        pending.model_copy(update={"state": ProfileState.AUTHENTICATED, "auth_type": "api_key"})
    )
    with pytest.raises(ProfileTransitionConflict):
        await store.mark_pending_error(profile_id, expected_generation=generation_a2)
    survivor = await store.get(ACCOUNT_ID, "anthropic", "work")
    assert survivor is not None
    assert survivor.state is ProfileState.AUTHENTICATED
    assert survivor.auth_type == "api_key"

    # Schedule 3 — the profile was deleted before A failed: never resurrect it.
    generation_a3 = await store.begin_pending(pending)
    await store.remove(profile_id)
    with pytest.raises(ProfileTransitionConflict):
        await store.mark_pending_error(profile_id, expected_generation=generation_a3)
    assert await store.get(ACCOUNT_ID, "anthropic", "work") is None  # no resurrection


@pytest.mark.asyncio
async def test_mark_pending_error_marks_owned_pending_profile(credential_blobs) -> None:
    """The still-owning failing flow transitions its own pending profile to ERROR."""
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    profile_id = profile_id_for(ACCOUNT_ID, "anthropic", "work")
    pending = Profile(
        id=profile_id,
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="work",
        state=ProfileState.PENDING,
    )
    generation = await store.begin_pending(pending)
    await store.mark_pending_error(profile_id, expected_generation=generation)
    errored = await store.get(ACCOUNT_ID, "anthropic", "work")
    assert errored is not None
    assert errored.state is ProfileState.ERROR


@pytest.mark.asyncio
async def test_authenticate_pending_publishes_last_refreshed_at_into_owner_fence(
    credential_blobs,
) -> None:
    """OME-307 M-1 — the authenticated owner's refresh timestamp must survive publication.

    FEATURE: profile OAuth authentication with concurrent-refresh safety.
    STORY: as a user who re-authenticates a profile via OAuth while an earlier credential
    refresh is still in flight, the earlier refresh's failure must not error the profile I
    just re-authenticated.

    INVARIANT: ``authenticate_pending`` publishes ``last_refreshed_at`` inside the SAME atomic
    CAS that flips PENDING->AUTHENTICATED, so the timestamp joins ``mark_authenticated_error``'s
    ownership fence (state + auth_type + last_refreshed_at). A stale refresh-failure carrying
    the pre-re-auth timestamp (here the pending row's ``None``) can then no longer match the
    fence: it is rejected with ``ProfileTransitionConflict`` and the freshly authenticated
    profile stays AUTHENTICATED. Dropping the field at publication would leave the row at the
    stale ``None`` and let the stale failure win.
    """
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    pending = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "work"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="work",
        state=ProfileState.PENDING,
    )
    generation = await store.begin_pending(pending)

    # The OAuth callback stamps a fresh refresh time on the authenticated form it publishes.
    refreshed_at = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
    authenticated = pending.model_copy(
        update={
            "state": ProfileState.AUTHENTICATED,
            "auth_type": "oauth",
            "last_refreshed_at": refreshed_at,
        }
    )
    await store.authenticate_pending(authenticated, expected_generation=generation)

    published = await store.get(ACCOUNT_ID, "anthropic", "work")
    assert published is not None
    assert published.state is ProfileState.AUTHENTICATED
    # The owner's refresh timestamp is durably published, not dropped to the pending ``None``.
    assert published.last_refreshed_at == refreshed_at

    # A stale refresh-failure that read the profile BEFORE re-auth (last_refreshed_at is None)
    # must NOT be able to error the new owner.
    with pytest.raises(ProfileTransitionConflict):
        await store.mark_authenticated_error(
            published.id,
            expected_auth_type="oauth",
            expected_last_refreshed_at=None,
        )
    still_authenticated = await store.get(ACCOUNT_ID, "anthropic", "work")
    assert still_authenticated is not None
    assert still_authenticated.state is ProfileState.AUTHENTICATED

    # The CURRENT owner (matching timestamp) can still legitimately error it — proving the
    # fence stayed functional, not merely always-closed.
    await store.mark_authenticated_error(
        published.id,
        expected_auth_type="oauth",
        expected_last_refreshed_at=refreshed_at,
    )
    errored = await store.get(ACCOUNT_ID, "anthropic", "work")
    assert errored is not None
    assert errored.state is ProfileState.ERROR
