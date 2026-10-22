"""The history purge's fence on PostgreSQL: no key is lost to a concurrent reference (E5b, C3/C4).

# FEATURE: OME-1138 Stage E history cleanup — the purge deletes an account's unaddressed blobs in
# one transaction that first takes `SELECT … FOR UPDATE` on the account row. Every reference
# creator inserts a row whose foreign key names that account, which takes `FOR KEY SHARE` on it, so
# the two serialize: an insert that comes second waits for the purge and then writes its key into a
# fresh row; a purge that comes second waits for the insert's commit, then sees the row and keeps
# the blob.
# INVARIANT (C4): a backfill that classified a `none` pair before the purge and inserts its
# Connection after it still reads its key, because the purge skipped that account.
# WHY PostgreSQL: SQLite has no row locks (C7). Fixtures are bound from the S2'c module; one
# container per module, so every test seeds an account of its own. Run with `AIGW_TEST_PG=1`.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import pytest
import test_provider_access_backing_postgres as backing
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tortoise.transactions import in_transaction

from aigateway.core.auth.models import Account
from aigateway.core.credential_names import profile_id_for
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.profile_models import Profile, ProfileState
from aigateway.core.provider_access.backfill_apply import apply_account
from aigateway.core.provider_access.backfill_classify import BackfillContext
from aigateway.core.provider_access.connection_locator import credential_blob_address
from aigateway.core.provider_access.history_purge import PurgeContext, purge_account
from aigateway.core.provider_access.pair_authority import PairAuthorityStore

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client

PROVIDER = "anthropic"
KEY = "sk-ant-api03-purge-fence-key-2468"
WAIT = 20
# WHY a pause, not an event: a blocked statement signals nothing; the proof is that it has NOT
# finished after the other side had ample time.
BLOCKED_FOR = 1.0
NO_ROWS = {"index_rows": 0, "name_shaped_blobs": 0, "uuid_shaped_blobs": 0}


async def _new_account() -> str:
    account_id = str(uuid4())
    await Account.create(id=account_id, username=f"purge-{account_id[:8]}", password_hash="x")
    return account_id


async def _seed_candidate(app: FastAPI) -> tuple[str, str]:
    """A fresh account and one blob of it that no Connection addresses — the purge's candidate."""
    account_id = await _new_account()
    candidate = credential_locator_for(PROVIDER, account_id, uuid4())["service"]
    await app.state.credential_store.write(candidate, "default", backing._api_key_blob("old-key"))
    return account_id, candidate


async def _adopt(
    app: FastAPI,
    account_id: str,
    service: str,
    *,
    entered: threading.Event,
    hold: Callable[[], Awaitable[None]] | None = None,
) -> UUID:
    """A reference creator: insert a Connection naming `service`, then write its key there."""
    connection_id = uuid4()
    async with in_transaction():
        entered.set()
        await OAuthConnection.create(
            id=connection_id,
            account_id=account_id,
            provider=PROVIDER,
            label="adopter",
            status="active",
            auth_type="api_key",
            credential_locator={"service": service, "account": "default"},
        )
        await app.state.credential_store.write(service, "default", backing._api_key_blob(KEY))
        if hold is not None:
            await hold()
    return connection_id


def _held_until(release: threading.Event) -> Callable[[], Awaitable[None]]:
    async def hold() -> None:
        if not await asyncio.to_thread(release.wait, WAIT):
            raise TimeoutError("never released")

    return hold


def _key_at(client: TestClient, service: str) -> str | None:
    raw = backing._call(
        client, backing._app(client).state.credential_store.read, service, "default"
    )
    return None if raw is None else json.loads(raw)["api_key"]


def test_a_reference_made_while_the_purge_holds_the_account_waits_and_keeps_its_key(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = backing._app(pg_client)
    account_id, candidate = backing._call(pg_client, _seed_candidate, app)
    ctx = PurgeContext.build(app, app.state.providers)
    locked, release, entered = threading.Event(), threading.Event(), threading.Event()
    real_list = PairAuthorityStore.list

    async def list_markers(store: PairAuthorityStore, *args: Any, **kwargs: Any) -> Any:
        # The purge holds the account row FOR UPDATE by now; nothing is deleted yet.
        locked.set()
        if not await asyncio.to_thread(release.wait, WAIT):
            raise TimeoutError("the purge was never released")
        return await real_list(store, *args, **kwargs)

    monkeypatch.setattr(PairAuthorityStore, "list", list_markers)
    with ThreadPoolExecutor(max_workers=2) as executor:
        purge = executor.submit(
            backing._call, pg_client, purge_account, ctx, account_id, apply=True
        )
        assert locked.wait(WAIT), "the purge never took the account lock"
        adopter = executor.submit(
            backing._call, pg_client, _adopt, app, account_id, candidate, entered=entered
        )
        assert entered.wait(WAIT), "the reference creator never started"
        time.sleep(BLOCKED_FOR)
        # INVARIANT (C3): the insert needs FOR KEY SHARE on the account row the purge holds.
        assert not adopter.done()
        release.set()
        purged = purge.result(timeout=30)
        adopter.result(timeout=30)

    assert (purged.skipped, purged.rows) == (None, {**NO_ROWS, "uuid_shaped_blobs": 1})
    # The purge deleted the old row; the waiting writer then wrote its key into a fresh one.
    assert _key_at(pg_client, candidate) == KEY


def test_a_purge_that_comes_second_waits_for_the_reference_and_keeps_the_blob(
    pg_client: TestClient,
) -> None:
    app = backing._app(pg_client)
    account_id, candidate = backing._call(pg_client, _seed_candidate, app)
    ctx = PurgeContext.build(app, app.state.providers)
    entered, release = threading.Event(), threading.Event()
    written = threading.Event()

    async def hold() -> None:
        written.set()
        await _held_until(release)()

    with ThreadPoolExecutor(max_workers=2) as executor:
        adopter = executor.submit(
            backing._call, pg_client, _adopt, app, account_id, candidate, entered=entered, hold=hold
        )
        # The reference is inserted and its key written, neither committed.
        assert written.wait(WAIT), "the reference creator never wrote its key"
        purge = executor.submit(
            backing._call, pg_client, purge_account, ctx, account_id, apply=True
        )
        time.sleep(BLOCKED_FOR)
        # INVARIANT (C3): the purge's FOR UPDATE waits for the uncommitted insert's FOR KEY SHARE.
        assert not purge.done()
        release.set()
        adopter.result(timeout=30)
        purged = purge.result(timeout=30)

    assert (purged.skipped, purged.rows) == (None, NO_ROWS)
    assert _key_at(pg_client, candidate) == KEY


async def _seed_profile_only(app: FastAPI) -> str:
    """A fresh account whose `none` pair has a document and its blob, and no Connection."""
    account_id = await _new_account()
    locator = credential_locator_for(PROVIDER, account_id, "default")
    await app.state.credential_store.write(
        locator["service"], locator["account"], backing._oauth_blob("tok")
    )
    await backing._index(app).upsert(
        Profile(
            id=profile_id_for(account_id, PROVIDER, "default"),
            account_id=account_id,
            provider=PROVIDER,
            name="default",
            state=ProfileState.AUTHENTICATED,
        )
    )
    return account_id


async def _token_through_locator(app: FastAPI, account_id: str, connection_id: UUID) -> Any:
    connection = await OAuthConnectionStore().get(account_id, connection_id)
    assert connection is not None
    plugin = app.state.providers.get(PROVIDER)
    address = credential_blob_address(app, plugin, PROVIDER, connection)
    assert address is not None
    raw = await app.state.credential_store.read(*address)
    return None if raw is None else json.loads(raw)["access_token"]


def test_a_backfill_that_classified_before_the_purge_still_reads_its_key(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = backing._app(pg_client)
    account_id = backing._call(pg_client, _seed_profile_only, app)
    backfill_ctx = BackfillContext.from_stores(app.state.credential_store, app.state.providers)
    purge_ctx = PurgeContext.build(app, app.state.providers)
    classified, release = threading.Event(), threading.Event()
    real_create = OAuthConnectionStore.create_pending

    async def create_pending(store: OAuthConnectionStore, *args: Any, **kwargs: Any) -> Any:
        # The backfill classified the pair `profile_only` and is about to insert its Connection.
        classified.set()
        if not await asyncio.to_thread(release.wait, WAIT):
            raise TimeoutError("the backfill was never released")
        return await real_create(store, *args, **kwargs)

    monkeypatch.setattr(OAuthConnectionStore, "create_pending", create_pending)
    with ThreadPoolExecutor(max_workers=1) as executor:
        backfill = executor.submit(
            backing._call, pg_client, apply_account, backfill_ctx, account_id
        )
        assert classified.wait(WAIT), "the backfill never reached its Connection insert"
        purged = backing._call(pg_client, purge_account, purge_ctx, account_id, apply=True)
        release.set()
        result = backfill.result(timeout=30)

    # INVARIANT (C4): the purge refused the account rather than delete the blob the backfill adopts.
    assert purged.skipped == "unmigrated_document"
    (record,) = result.records
    assert (record.category, record.applied) == ("profile_only", True)
    assert record.connection_id is not None
    token = backing._call(
        pg_client, _token_through_locator, app, account_id, UUID(record.connection_id)
    )
    assert token == "tok"
