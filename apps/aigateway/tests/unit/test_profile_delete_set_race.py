"""OME-307 Unit 3 — atomic profile deletion versus a racing API-key set.

FEATURE: deleting a profile (credential blob + profile-index entry) and setting an API key
on the same profile.
STORY: as a user who deletes a profile while an API-key set for that same profile is still
in flight, the delete wins cleanly — no encrypted credential is left behind with no profile,
and the older API-key writer does not silently resurrect the profile I just deleted.

INVARIANT: credential deletion and profile-index removal are published in ONE transaction,
so a committed delete never leaves an orphan credential. An API-key publication that
observed the profile as existing must NOT recreate it if a concurrent delete removed it
first; it aborts with ProfileTransitionConflict (the retryable conflict), and its own
credential write rolls back. This is the profile analogue of the connection delete /
set-api-key CAS the codebase already relies on.

WHY a store double: the gateway test harness is SQLite-only and serializes whole
transactions on one connection, so it cannot exhibit the PostgreSQL per-row interleaving
this race needs (review requirement). ``_PostgresRowLockStore`` models the relevant PostgreSQL
READ COMMITTED behavior — an UPDATE/DELETE inside a transaction takes that row's lock until
COMMIT, and the transaction rolls back its own row writes on failure — so two independent
tasks contend exactly as two PostgreSQL backends would, on the same event loop.

The two route-level tests (the HTTP delete removing blob and index entry, and a delete winning
over a stale PATCH) retired at OME-1209 Stage E3 with the Profile DELETE and PATCH routes, which
answer 410 `legacy_profile_api_retired` since then (`test_legacy_profile_routes_retired.py`). The
native successors are `test_oauth_connection_api_key_routes.py`
(`test_delete_api_key_connection_removes_blob`) and `test_api_key_connection_races.py`
(`test_delete_wins_over_inflight_key_replacement`).
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import pytest

from aigateway.core.credential_names import profile_id_for
from aigateway.core.profile_index import (
    INDEX_CREDENTIAL_SERVICE,
    ProfileIndexStore,
    ProfileTransitionConflict,
)
from aigateway.core.profile_models import Profile, ProfileState

from ._pg_mvcc_store import MvccRowStore

ACCOUNT_ID = "account-1"
# A stand-in for the profile's credential-blob slot (the chat path's real slot); only its
# identity as a distinct contended row matters for modelling the race.
CRED_SERVICE = "aigateway:anthropic:cred"
CRED_ACCOUNT = "default"

# Per-task transaction scratch: row locks held until commit plus the pre-images needed to
# roll back this task's own writes. A ContextVar is task-local under asyncio, mirroring how
# in_transaction() pins one pooled connection per task.
_open_txn: contextvars.ContextVar[dict | None] = contextvars.ContextVar("_open_txn", default=None)


class _PostgresRowLockStore:
    """Credential-store double modelling PostgreSQL READ COMMITTED row locking + rollback."""

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}
        self._row_locks: dict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)

    @contextlib.asynccontextmanager
    async def transaction(self):
        # WHY: models ``async with in_transaction()``. Row locks taken by mutate() during the
        # body are held until this block exits (COMMIT); on failure the block's own writes are
        # rolled back from their recorded pre-images before the locks release.
        txn: dict = {"held": [], "undo": {}}
        token = _open_txn.set(txn)
        try:
            yield
        except BaseException:
            for key, prior in txn["undo"].items():
                if prior is None:
                    self.data.pop(key, None)
                else:
                    self.data[key] = prior
            raise
        finally:
            _open_txn.reset(token)
            for lock in txn["held"]:
                lock.release()

    async def read(self, service: str, account: str) -> str | None:
        await asyncio.sleep(0)
        return self.data.get((service, account))

    async def write(self, service: str, account: str, value: str) -> None:
        await asyncio.sleep(0)
        self.data[(service, account)] = value

    async def delete(self, service: str, account: str) -> None:
        await asyncio.sleep(0)
        self.data.pop((service, account), None)

    async def mutate(self, service, account, mutator) -> None:
        key = (service, account)
        row_lock = self._row_locks[key]
        txn = _open_txn.get()
        reused = txn is not None and row_lock in txn["held"]
        if not reused:
            # UPDATE/DELETE takes the row lock (blocks while another txn holds it uncommitted).
            await row_lock.acquire()
        try:
            await asyncio.sleep(0)  # yield between "SELECT" and "UPDATE" as real I/O would
            prior = self.data.get(key)
            if txn is not None and key not in txn["undo"]:
                txn["undo"][key] = prior  # record pre-image once, for rollback
            next_value = mutator(prior)
            if next_value is None:
                self.data.pop(key, None)
            else:
                self.data[key] = next_value
        finally:
            if txn is None:
                row_lock.release()  # autocommit statement: released at statement end
            elif not reused:
                txn["held"].append(row_lock)  # inside a txn: hold until COMMIT


def _authenticated_oauth(name: str) -> Profile:
    return Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", name),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name=name,
        state=ProfileState.AUTHENTICATED,
        auth_type="oauth",
    )


def _api_key(name: str) -> Profile:
    return Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", name),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name=name,
        state=ProfileState.AUTHENTICATED,
        auth_type="api_key",
    )


@pytest.mark.asyncio
async def test_concurrent_delete_and_api_key_set_leaves_no_orphan_or_resurrection() -> None:
    """Concrete schedule (delete grabs the credential row lock first, deterministically):

      1. DELETE opens its transaction and takes the credential row lock (its credential
         delete), then yields.
      2. SET opens its transaction and blocks acquiring the same credential row lock.
      3. DELETE removes the profile-index entry and COMMITS, releasing both row locks.
      4. SET wins the credential row lock, writes its API-key blob, then its profile-index
         publication observes the profile already gone. Because SET observed the profile as
         existing when it began, it must NOT resurrect it: it raises ProfileTransitionConflict
         and its transaction rolls back the API-key blob it just wrote.

    Final committed state: profile gone, credential gone — delete won with no orphan.
    """
    store = _PostgresRowLockStore()
    index = ProfileIndexStore(credential_store=store)

    await index.upsert(_authenticated_oauth("work"))
    await store.write(CRED_SERVICE, CRED_ACCOUNT, "oauth-token-blob")
    profile_id = profile_id_for(ACCOUNT_ID, "anthropic", "work")

    async def delete_op() -> None:
        # Mirror delete_profile: credential delete + index removal in one transaction.
        async with store.transaction():
            await store.mutate(CRED_SERVICE, CRED_ACCOUNT, lambda _current: None)
            await index.remove(profile_id)

    async def set_op() -> None:
        # Mirror set_profile_api_key updating an OBSERVED-existing profile: persist the
        # API-key blob, then publish conditionally so a concurrent delete wins.
        async with store.transaction():
            await store.mutate(CRED_SERVICE, CRED_ACCOUNT, lambda _current: "api-key-blob")
            await index.upsert(_api_key("work"), require_present=True)

    results = await asyncio.gather(delete_op(), set_op(), return_exceptions=True)

    assert results[0] is None, f"delete unexpectedly failed: {results[0]!r}"
    assert isinstance(results[1], ProfileTransitionConflict), (
        f"set should abort rather than resurrect, got {results[1]!r}"
    )
    # Delete won cleanly: profile removed AND no orphan credential blob survived.
    assert await index.get(ACCOUNT_ID, "anthropic", "work") is None
    assert store.data.get((CRED_SERVICE, CRED_ACCOUNT)) is None
    assert (INDEX_CREDENTIAL_SERVICE, f"account:{ACCOUNT_ID}") in store.data


@pytest.mark.asyncio
async def test_api_key_publication_still_creates_a_genuinely_new_profile() -> None:
    """require_present must gate ONLY the update path: a first-time API-key set (the profile
    was never observed) still creates the profile — absence is not a conflict there."""
    store = _PostgresRowLockStore()
    index = ProfileIndexStore(credential_store=store)

    # No prior profile: a fresh create passes require_present=False.
    await index.upsert(_api_key("fresh"), require_present=False)
    assert await index.get(ACCOUNT_ID, "anthropic", "fresh") is not None

    # And updating an existing profile with require_present=True succeeds when it is present.
    await index.upsert(_authenticated_oauth("fresh"), require_present=True)
    updated = await index.get(ACCOUNT_ID, "anthropic", "fresh")
    assert updated is not None
    assert updated.auth_type == "oauth"


async def _seed_oauth_profile_without_credential(store) -> str:
    """Seed an index row holding an OAuth profile whose credential slot is ABSENT.

    A pending/errored OAuth profile legitimately has an index entry but no credential blob —
    the credential-absent state the review requires. The index row (always present) is seeded;
    the credential row is deliberately NOT written.
    """
    seeder = ProfileIndexStore(credential_store=store)
    await seeder.upsert(_authenticated_oauth("work"))
    return profile_id_for(ACCOUNT_ID, "anthropic", "work")


@pytest.mark.asyncio
async def test_delete_wins_over_set_when_delete_commits_first_credential_absent() -> None:
    """OME-307 Blocker 3 — credential row ABSENT, ``delete_profile`` commits first.

    Production ordering under test (index-row CAS FIRST, credential write/delete SECOND):

      1. DELETE acquires the always-present index-row lock and removes the profile, then its
         credential delete finds NO credential row (absent) — a no-op that takes no lock — and
         COMMITS. Profile gone.
      2. SET was blocked on the index-row lock; it now runs and re-evaluates require_present
         against the committed index. The profile is gone, so it raises
         ProfileTransitionConflict and rolls back — it must NOT resurrect the deleted profile
         and its API-key blob write is never committed.

    Final state: profile gone, credential absent — delete wins, no orphan, no resurrection.
    Serializing on the credential row instead would fail here: the missing-row delete takes no
    lock, so SET's later INSERT would not be serialized and would orphan a credential.
    """
    store = MvccRowStore()
    profile_id = await _seed_oauth_profile_without_credential(store)
    index_del = ProfileIndexStore(credential_store=store)
    index_set = ProfileIndexStore(credential_store=store)
    delete_holds_index = asyncio.Event()

    async def delete_op() -> None:
        async with store.transaction():
            await index_del.remove(profile_id)  # index-row CAS FIRST (always-present row)
            delete_holds_index.set()
            await store.delete(CRED_SERVICE, CRED_ACCOUNT)  # credential SECOND (absent -> no-op)

    async def set_op() -> None:
        await delete_holds_index.wait()  # DELETE takes the index-row lock first, deterministically
        async with store.transaction():
            await index_set.upsert(_api_key("work"), require_present=True)  # blocks, then conflicts
            await store.write(CRED_SERVICE, CRED_ACCOUNT, "api-key-blob")

    results = await asyncio.gather(delete_op(), set_op(), return_exceptions=True)

    assert results[0] is None, f"delete unexpectedly failed: {results[0]!r}"
    assert isinstance(results[1], ProfileTransitionConflict), (
        f"set must abort rather than resurrect, got {results[1]!r}"
    )
    assert await index_set.get(ACCOUNT_ID, "anthropic", "work") is None
    assert store.committed.get((CRED_SERVICE, CRED_ACCOUNT)) is None  # no orphan credential
    assert (INDEX_CREDENTIAL_SERVICE, f"account:{ACCOUNT_ID}") in store.committed


@pytest.mark.asyncio
async def test_delete_wins_over_set_when_set_commits_first_credential_absent() -> None:
    """OME-307 Blocker 3 — credential row ABSENT, the API-key ``set`` commits first.

    Production ordering under test (index-row CAS FIRST, credential write/delete SECOND):

      1. SET acquires the index-row lock, updates the profile to api_key, writes (INSERTs) its
         credential blob, and COMMITS.
      2. DELETE was blocked on the index-row lock; it now removes the profile and — because
         SET's credential blob is now COMMITTED and visible — deletes it too, then COMMITS.

    Final state: profile gone, credential gone — the later delete still cleans up SET's blob,
    so no orphan survives. This is the commit order the credential-first ordering handles
    correctly only when the blob already exists; here it is created mid-race.
    """
    store = MvccRowStore()
    profile_id = await _seed_oauth_profile_without_credential(store)
    index_set = ProfileIndexStore(credential_store=store)
    index_del = ProfileIndexStore(credential_store=store)
    set_holds_index = asyncio.Event()

    async def set_op() -> None:
        async with store.transaction():
            await index_set.upsert(_api_key("work"), require_present=True)  # index-row CAS FIRST
            set_holds_index.set()
            await store.write(CRED_SERVICE, CRED_ACCOUNT, "api-key-blob")  # credential SECOND

    async def delete_op() -> None:
        await set_holds_index.wait()  # SET takes the index-row lock first, deterministically
        async with store.transaction():
            await index_del.remove(profile_id)  # blocks until SET commits, then removes
            await store.delete(CRED_SERVICE, CRED_ACCOUNT)  # SET's blob now visible -> deleted

    results = await asyncio.gather(set_op(), delete_op(), return_exceptions=True)

    assert results[0] is None, f"set unexpectedly failed: {results[0]!r}"
    assert results[1] is None, f"delete unexpectedly failed: {results[1]!r}"
    assert await index_del.get(ACCOUNT_ID, "anthropic", "work") is None
    assert store.committed.get((CRED_SERVICE, CRED_ACCOUNT)) is None  # no orphan credential
    assert (INDEX_CREDENTIAL_SERVICE, f"account:{ACCOUNT_ID}") in store.committed


@pytest.mark.asyncio
async def test_stale_dispatch_error_cannot_delete_win_or_mark_newer_same_auth_owner() -> None:
    """Error publication must compare the credential version it actually used."""
    store = MvccRowStore()
    index = ProfileIndexStore(credential_store=store)
    profile_id = profile_id_for(ACCOUNT_ID, "anthropic", "work")
    old_refreshed_at = datetime.now(UTC) - timedelta(minutes=1)
    old = _api_key("work").model_copy(update={"last_refreshed_at": old_refreshed_at})
    await index.upsert(old)

    await index.remove(profile_id)
    with pytest.raises(ProfileTransitionConflict):
        await index.mark_authenticated_error(
            profile_id,
            expected_auth_type="api_key",
            expected_last_refreshed_at=old_refreshed_at,
        )
    assert await index.get(ACCOUNT_ID, "anthropic", "work") is None

    newer_refreshed_at = datetime.now(UTC)
    newer = old.model_copy(update={"last_refreshed_at": newer_refreshed_at})
    await index.upsert(newer)
    with pytest.raises(ProfileTransitionConflict):
        await index.mark_authenticated_error(
            profile_id,
            expected_auth_type="api_key",
            expected_last_refreshed_at=old_refreshed_at,
        )
    survivor = await index.get(ACCOUNT_ID, "anthropic", "work")
    assert survivor is not None
    assert survivor.state is ProfileState.AUTHENTICATED
    assert survivor.last_refreshed_at == newer_refreshed_at
