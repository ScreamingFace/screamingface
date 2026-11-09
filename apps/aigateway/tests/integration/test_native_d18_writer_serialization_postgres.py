"""Native creates serialize with D18 pair mutations on PostgreSQL (OME-1695 follow-up).

# INVARIANT: every writer of a migrated pair takes the marker row first. A native insert cannot
# appear after D18's live-set recheck but before commit and leave a Connection whose credential the
# pair mutation removed or superseded.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import pytest
import test_pair_admin_mutations_postgres as pair_admin
import test_provider_access_backing_postgres as backing
from fastapi.testclient import TestClient
from httpx import Response

import aigateway.core.provider_access.connection_native as connection_native
import aigateway.routes.oauth_connections as oauth_routes
from aigateway.core.oauth.store import credential_locator_for
from aigateway.core.provider_access import PairAuthorityStore, WriteConflict

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client

PROVIDER = backing.PROVIDER
NATIVE_KEY = "sk-ant-api03-native-d18-race-1111"


def _native_create(client: TestClient) -> Response:
    return client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": PROVIDER, "label": backing._fresh_name(), "api_key": NATIVE_KEY},
    )


def _blob(client: TestClient, locator: dict[str, str]) -> str | None:
    store = backing._app(client).state.credential_store
    return backing._call(client, store.read, locator["service"], locator["account"])


def test_native_create_waits_for_d18_delete_and_loses_its_stale_generation_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = pair_admin._fresh_pair(pg_client)
    seeded = pair_admin._bridge_put(pg_client, account_id)
    assert not isinstance(seeded, WriteConflict), seeded
    hold = backing._MarkerHold(monkeypatch, holds=lambda index, _kw: index == 0)
    native_attempted = threading.Event()
    connection_id = uuid4()
    real_hold = connection_native.hold_pair

    async def observed_hold(pair: Any) -> None:
        native_attempted.set()
        await real_hold(pair)

    monkeypatch.setattr(connection_native, "hold_pair", observed_hold)
    monkeypatch.setattr(oauth_routes, "uuid4", lambda: connection_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        deleting = executor.submit(pair_admin._bridge_delete, pg_client, account_id)
        assert hold.held.wait(20), "D18 DELETE never locked the pair marker"
        creating = executor.submit(_native_create, pg_client)
        assert native_attempted.wait(20), "native create never attempted the pair marker"
        hold.release.set()
        deleted = deleting.result(timeout=30)
        created = creating.result(timeout=30)

    assert not isinstance(deleted, WriteConflict), deleted
    assert getattr(created, "status_code", None) == 409, getattr(created, "text", created)
    assert created.json()["detail"]["code"] == "connection_conflict"
    assert pair_admin._live(pg_client, account_id) == []
    pair = backing._marker(pg_client, account_id)
    assert (pair.migration_state, pair.effective_connection_id, pair.generation) == (
        "migrated",
        None,
        2,
    )
    locator = credential_locator_for(PROVIDER, account_id, connection_id)
    assert _blob(pg_client, locator) is None


def test_d18_delete_waits_for_native_create_and_loses_its_stale_live_set_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = pair_admin._fresh_pair(pg_client)
    seeded = pair_admin._bridge_put(pg_client, account_id)
    assert not isinstance(seeded, WriteConflict), seeded
    before = backing._marker(pg_client, account_id)
    held = threading.Event()
    release = threading.Event()
    d18_attempted = threading.Event()
    real_hold = connection_native.hold_pair
    real_advance = PairAuthorityStore.advance

    async def held_pair(pair: Any) -> None:
        await real_hold(pair)
        held.set()
        if not await asyncio.to_thread(release.wait, 20):
            raise TimeoutError("native marker hold was not released")

    async def observed_advance(store: Any, *args: Any, **kwargs: Any) -> Any:
        d18_attempted.set()
        return await real_advance(store, *args, **kwargs)

    monkeypatch.setattr(connection_native, "hold_pair", held_pair)
    monkeypatch.setattr(PairAuthorityStore, "advance", observed_advance)

    with ThreadPoolExecutor(max_workers=2) as executor:
        creating = executor.submit(_native_create, pg_client)
        assert held.wait(20), "native create never locked the pair marker"
        deleting = executor.submit(pair_admin._bridge_delete, pg_client, account_id)
        assert d18_attempted.wait(20), "D18 DELETE never attempted the pair marker"
        release.set()
        created = creating.result(timeout=30)
        deleted = deleting.result(timeout=30)

    assert created.status_code == 201, created.text
    assert isinstance(deleted, WriteConflict) and deleted.kind == "superseded", deleted
    rows = pair_admin._live(pg_client, account_id)
    assert len(rows) == 2 and all(row.status == "active" for row in rows)
    pair = backing._marker(pg_client, account_id)
    assert (pair.effective_connection_id, pair.generation) == (
        before.effective_connection_id,
        before.generation,
    )
    created_id = created.json()["id"]
    native = next(row for row in rows if str(row.id) == created_id)
    assert _blob(pg_client, native.credential_locator) is not None
