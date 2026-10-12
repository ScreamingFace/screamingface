"""PostgreSQL races of the G0 refresh guard on an unmarked legacy pair (OME-1497, part 2).

# FEATURE: OME-1138 D18, G0 (contract §5.3 falsifier) — "an old refresh publication after a key
# replacement loses, including on an unmarked `none` pair (PostgreSQL lane)".
# INVARIANT: on READ COMMITTED the account index row is the serialization point: a replacement that
# committed during the refresh's provider window makes the publication lose; a publication that
# holds the index first commits, and the replacement that waited on it writes last.
# AIDEV-NOTE: fixtures and helpers are bound from the S2'c module; run with `AIGW_TEST_PG=1`.
"""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
import test_provider_access_backing_postgres as backing
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.profile_models import Profile, ProfileState, credential_name_for, profile_id_for
from aigateway.core.provider_access import ProfileRefreshOwner
from aigateway.core.provider_access.refresh_guard import GuardedRefreshPublication
from aigateway.plugins.anthropic_provider.auth import credential_service_for

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client

PROVIDER = backing.PROVIDER
KEY = "sk-ant-api03-postgres-refresh-key-9753"


async def _seed_legacy_oauth(app: FastAPI, account_id: str, name: str) -> None:
    await backing._reset_pair(app, account_id)
    await app.state.credential_store.write(
        credential_service_for(credential_name_for(account_id, name)),
        "default",
        backing._oauth_blob("old"),
    )
    await app.state.profile_index.upsert(
        Profile(
            id=profile_id_for(account_id, PROVIDER, name),
            account_id=account_id,
            provider=PROVIDER,
            name=name,
            state=ProfileState.AUTHENTICATED,
            auth_type="oauth",
        )
    )


def _refresh(client: TestClient, name: str) -> Any:
    return client.post(f"/v1/auth/{PROVIDER}/profiles/{name}/refresh")


def _put(client: TestClient, name: str) -> Any:
    return client.put(f"/v1/auth/{PROVIDER}/profiles/{name}/api-key", json={"api_key": KEY})


def _token_factory(before_answer: Any) -> Any:
    async def handler(_request: httpx.Request) -> httpx.Response:
        await before_answer()
        return httpx.Response(
            200,
            json={
                "access_token": "fresh",
                "refresh_token": "refresh-fresh",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0)
    )


def test_a_refresh_loses_to_a_key_replacement_committed_in_its_window_on_postgres(
    pg_client: TestClient,
) -> None:
    app = backing._app(pg_client)
    account_id = backing._account_id(pg_client)
    name = backing._fresh_name()
    backing._call(pg_client, _seed_legacy_oauth, app, account_id, name)

    async def replace_the_key() -> None:
        await app.state.provider_credential_admin.set_api_key(
            account_id, PROVIDER, raw_api_key=KEY, legacy_name=name
        )

    app.state.anthropic_http_factory = _token_factory(replace_the_key)

    resp = _refresh(pg_client, name)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "profile_conflict"
    blob = backing._profile_blob(pg_client, account_id, name)
    assert blob is not None and json.loads(blob)["api_key"] == KEY
    pair = backing._marker(pg_client, account_id)
    assert (pair.migration_state, pair.generation) == ("none", 1)


def test_a_key_replacement_waits_for_a_publishing_refresh_and_writes_last_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = backing._app(pg_client)
    account_id = backing._account_id(pg_client)
    name = backing._fresh_name()
    backing._call(pg_client, _seed_legacy_oauth, app, account_id, name)

    async def answer() -> None:
        return None

    app.state.anthropic_http_factory = _token_factory(answer)
    locked, release = threading.Event(), threading.Event()
    real_lock = ProfileRefreshOwner.lock

    async def lock_and_hold(self: ProfileRefreshOwner) -> None:
        await real_lock(self)
        locked.set()
        # WHY a thread wait: the publication must keep its index row lock while the PUT runs.
        await asyncio.to_thread(release.wait, 20)

    monkeypatch.setattr(ProfileRefreshOwner, "lock", lock_and_hold)
    with ThreadPoolExecutor(max_workers=2) as executor:
        refreshing = executor.submit(_refresh, pg_client, name)
        assert locked.wait(20), "the refresh never reached its publication"
        replacing = executor.submit(_put, pg_client, name)
        replacing_done = threading.Event()
        replacing.add_done_callback(lambda _f: replacing_done.set())
        # INVARIANT: the replacement cannot commit past the index row the publication holds.
        assert not replacing_done.wait(1.0), "the key replacement did not wait for the index"
        release.set()
        refreshed, replaced = refreshing.result(timeout=30), replacing.result(timeout=30)

    assert refreshed.status_code == 200, refreshed.text
    assert replaced.status_code == 200, replaced.text
    blob = backing._profile_blob(pg_client, account_id, name)
    assert blob is not None and json.loads(blob)["api_key"] == KEY
    assert backing._marker(pg_client, account_id).generation == 1
    # INVARIANT: the refresh stamped its metadata inside its own publication, so nothing after it
    # rewrites the document the replacement left as `api_key`.
    profiles = backing._call(pg_client, app.state.profile_index.list, account_id, PROVIDER)
    replaced_doc = next(p for p in profiles if p.name == name)
    assert replaced_doc.auth_type == "api_key"


def test_a_publishing_refresh_waits_for_a_delete_and_resurrects_nothing_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT (OME-307 H-1, now held by the guard): a delete that holds the account index when the
    # publication arrives commits first; the publication then finds no owner and writes nothing.
    app = backing._app(pg_client)
    account_id = backing._account_id(pg_client)
    name = backing._fresh_name()
    backing._call(pg_client, _seed_legacy_oauth, app, account_id, name)

    async def answer() -> None:
        return None

    app.state.anthropic_http_factory = _token_factory(answer)
    index = app.state.profile_index
    remove = index.remove
    delete_holds, publishing, release = threading.Event(), threading.Event(), threading.Event()

    async def remove_and_hold(profile_id: str) -> None:
        await remove(profile_id)
        delete_holds.set()
        await asyncio.to_thread(release.wait, 20)

    real_publish = GuardedRefreshPublication.publish

    async def signal_then_publish(self: Any, captured: object, write: Any) -> None:
        # WHY at the publication's entry: a marked pair waits on the marker before the owner lock.
        publishing.set()
        await real_publish(self, captured, write)

    monkeypatch.setattr(index, "remove", remove_and_hold)
    monkeypatch.setattr(GuardedRefreshPublication, "publish", signal_then_publish)
    with ThreadPoolExecutor(max_workers=2) as executor:
        deleting = executor.submit(pg_client.delete, f"/v1/auth/{PROVIDER}/profiles/{name}")
        assert delete_holds.wait(20), "the delete never took the index row"
        refreshing = executor.submit(_refresh, pg_client, name)
        assert publishing.wait(20), "the refresh never reached its publication"
        release.set()
        deleted, refreshed = deleting.result(timeout=30), refreshing.result(timeout=30)

    assert deleted.status_code == 204, deleted.text
    assert refreshed.status_code == 409, refreshed.text
    assert refreshed.json()["detail"]["code"] == "profile_conflict"
    assert pg_client.get(f"/v1/auth/{PROVIDER}/profiles/{name}").status_code == 404
    assert backing._profile_blob(pg_client, account_id, name) is None
