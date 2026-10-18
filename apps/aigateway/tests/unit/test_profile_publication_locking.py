"""OME-307 Unit 1 — profile publication must not deadlock under PostgreSQL row locking.

FEATURE: OAuth/API-key profile publication (credential blob + profile-index write).
STORY: as an operator completing two profile authentications for the same account on a
PostgreSQL-backed gateway worker, both publications complete instead of deadlocking.

INVARIANT: ``ProfileIndexStore.authenticate_pending`` performs exactly ONE conditional
durable publication under a SINGLE acquisition of the process ``asyncio.Lock``. It must
never RELEASE that lock and then RE-ACQUIRE it while the enclosing OAuth transaction
(``routes/auth.py`` ``_complete_oauth_for_app`` → ``in_transaction()``) still holds the
profile-index row lock. A second acquisition inverts the application-lock / database-
row-lock order between two concurrent writers and deadlocks: on PostgreSQL the waiter
that holds the process lock is blocked *in-process*, invisible to the database deadlock
detector, so nothing ever breaks the cycle.

WHY a store double: the gateway test harness is SQLite-only (``conftest``), and SQLite
serializes whole transactions on one global connection lock, so it *cannot* exhibit the
PostgreSQL per-row inversion — using it as evidence would be unsound (review requirement).
``_PostgresRowLockStore`` below models the relevant PostgreSQL READ COMMITTED behavior: an UPDATE
(``mutate``) executed inside a transaction takes that row's lock and holds it until the
transaction COMMITs, so an independent task's UPDATE on the same row blocks until the
first commits — exactly as two PostgreSQL backends contend. No database or service is
added; this runs on the same event loop as every other unit test.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
from collections import defaultdict
from functools import partial

import httpx
import pytest

import aigateway.routes.auth as auth_module
from aigateway.core.credential_names import profile_id_for
from aigateway.core.profile_index import INDEX_CREDENTIAL_SERVICE, ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState

from .oauth_flow_seed import open_oauth_flow

ACCOUNT_ID = "account-1"

# Per-task transaction scratch: the list of row locks acquired by the current task's
# open transaction, released together on commit. A ContextVar is task-local under
# asyncio (each task runs with its own copy), which mirrors how ``in_transaction()``
# pins one pooled connection per task.
_open_txn: contextvars.ContextVar[list[asyncio.Lock] | None] = contextvars.ContextVar(
    "_open_txn", default=None
)


class _PostgresRowLockStore:
    """Credential-store double modelling PostgreSQL READ COMMITTED row locking.

    ``ProfileIndexStore`` read-modify-writes the account index row through ``mutate``.
    On PostgreSQL the conditional UPDATE inside the enclosing transaction takes a row
    lock held until COMMIT; we reproduce that so two independent tasks contend on the
    row exactly as two PG backends would.
    """

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}
        self._row_locks: dict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)

    @contextlib.asynccontextmanager
    async def transaction(self):
        # WHY: models ``async with in_transaction()`` around the publication. Row locks
        # acquired by mutate() during the body are held until this block exits (COMMIT).
        held: list[asyncio.Lock] = []
        token = _open_txn.set(held)
        try:
            yield
        finally:
            _open_txn.reset(token)
            for lock in held:
                lock.release()

    async def read(self, service: str, account: str) -> str | None:
        await asyncio.sleep(0)  # force interleaving between read and write, like real I/O
        return self.data.get((service, account))

    async def write(self, service: str, account: str, value: str) -> None:
        await asyncio.sleep(0)
        self.data[(service, account)] = value

    async def delete(self, service: str, account: str) -> None:
        self.data.pop((service, account), None)

    async def mutate(self, service, account, mutator) -> None:
        key = (service, account)
        row_lock = self._row_locks[key]
        held = _open_txn.get()
        reused = held is not None and row_lock in held
        if not reused:
            # UPDATE takes the row lock (blocks if another txn holds it uncommitted).
            await row_lock.acquire()
        try:
            await asyncio.sleep(0)  # yield between "SELECT" and "UPDATE" as real I/O would
            next_value = mutator(self.data.get(key))
            if next_value is None:
                self.data.pop(key, None)
            else:
                self.data[key] = next_value
        finally:
            if held is None:
                row_lock.release()  # autocommit statement: lock released at statement end
            elif not reused:
                held.append(row_lock)  # inside a txn: hold until COMMIT


def _pending(name: str) -> Profile:
    return Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", name),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name=name,
        state=ProfileState.PENDING,
    )


def _authenticated(name: str) -> Profile:
    return Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", name),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name=name,
        state=ProfileState.AUTHENTICATED,
        auth_type="oauth",
    )


@pytest.mark.asyncio
async def test_concurrent_pending_publications_do_not_deadlock() -> None:
    """Two OAuth callbacks for the same account, publishing inside their own PostgreSQL
    transactions, must both complete.

    Concrete schedule the pre-fix code deadlocks on:
      1. Task A acquires the process lock, then yields inside its first index read.
      2. Task B starts, blocks acquiring the same process lock (FIFO waiter).
      3. Task A's conditional mutate takes the index ROW lock (held until A commits),
         then A releases the process lock at the end of its ``async with`` block.
      4. B (the queued waiter) wins the process lock ahead of A.
      5. Pre-fix ONLY: A now re-enters ``self.upsert`` and blocks re-acquiring the
         process lock (held by B).
      6. B's mutate blocks on the index row lock (held by A's uncommitted transaction).
      => A waits on the process lock (B holds it); B waits on the row lock (A's txn
         holds it). The cycle is invisible to PostgreSQL — permanent deadlock.
    With a single acquisition (post-fix) A releases the process lock before it commits
    and never needs it again, so B always makes progress.
    """
    store = _PostgresRowLockStore()
    index = ProfileIndexStore(credential_store=store)

    # Seed two still-pending profiles on the same account index row (no contention yet).
    await index.upsert(_pending("one"))
    await index.upsert(_pending("two"))

    async def publish(profile: Profile) -> None:
        # Mirror _complete_oauth_for_app: publication runs inside the DB transaction.
        async with store.transaction():
            await index.authenticate_pending(profile)

    try:
        await asyncio.wait_for(
            asyncio.gather(publish(_authenticated("one")), publish(_authenticated("two"))),
            timeout=3.0,
        )
    except TimeoutError:  # pragma: no cover - only hit against the pre-fix code
        pytest.fail(
            "profile publication deadlocked: authenticate_pending re-acquired the "
            "process lock while the enclosing transaction still held the index row "
            "lock (OME-307 Unit 1 lock-order inversion)"
        )

    # Both pending profiles were durably authenticated, and exactly one index row exists.
    both = {p.name: p.state for p in await index.list(ACCOUNT_ID)}
    assert both == {"one": ProfileState.AUTHENTICATED, "two": ProfileState.AUTHENTICATED}
    assert (INDEX_CREDENTIAL_SERVICE, f"account:{ACCOUNT_ID}") in store.data


def test_oauth_profile_completion_locks_index_before_optional_credential(
    authenticated_client,
    monkeypatch,
) -> None:
    """OAuth completion must share profile set/delete's stable-row-first lock order.

    INVARIANT: every profile lifecycle transaction mutates the always-present account index row
    before touching the optional credential row. Credential-first OAuth completion can deadlock
    against index-first API-key set/delete on PostgreSQL.
    """
    calls: list[str] = []
    index = authenticated_client.app.state.profile_index
    authenticate_pending = index.authenticate_pending
    persist_credentials = auth_module.persist_credentials_or_503

    async def _record_index(profile, **kwargs) -> None:
        calls.append("index")
        await authenticate_pending(profile, **kwargs)

    async def _record_credential(*args, **kwargs) -> None:
        if kwargs.get("description") == "OAuth profile credentials":
            calls.append("credential")
        await persist_credentials(*args, **kwargs)

    async def _token_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "oauth-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    monkeypatch.setattr(index, "authenticate_pending", _record_index)
    monkeypatch.setattr(auth_module, "persist_credentials_or_503", _record_credential)
    authenticated_client.app.state.anthropic_http_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(_token_handler), timeout=httpx.Timeout(5.0)
    )

    # WHY: the Profile OAuth start route answers 410 since OME-1209 Stage E3; the seeder leaves
    # the pending document and entry it left, and the legacy-pending callback still ships.
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    state = authenticated_client.portal.call(
        partial(
            open_oauth_flow,
            authenticated_client.app,
            account_id=account_id,
            provider="anthropic",
            name="work",
        )
    )
    completed = authenticated_client.get(
        "/v1/auth/anthropic/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )

    assert completed.status_code == 200
    assert calls == ["index", "credential"]
