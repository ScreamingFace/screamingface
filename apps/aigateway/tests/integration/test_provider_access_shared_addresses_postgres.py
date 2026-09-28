"""Retiring a superseded errored row keeps the one lock order on PostgreSQL (OME-1208, R1).

# FEATURE: PR #1029 review — a Profile-facade OAuth start on a migrated pair RETIRES the `error`
# row it supersedes (D-R1-1). That retirement is a row write, so it must come AFTER the marker,
# like every other authority writer (marker → index → connection row → blob).
# INVARIANT (D14): whoever holds the marker row decides; the other writer re-evaluates its
# `WHERE generation = <stale>` to zero rows and answers 409. Revoking the row BEFORE the marker
# would invert the order against a native key replacement (marker, then row) and deadlock.
# AIDEV-NOTE: fixtures and helpers are bound from the S2'c module; run with `AIGW_TEST_PG=1`.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import pytest
import test_provider_access_backing_postgres as backing
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tortoise import connections

from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.profile_models import credential_name_for
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.routes import oauth_connections as oauth_routes

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client

PROVIDER = backing.PROVIDER
OLD_KEY = "sk-ant-api03-postgres-rejected-key-1111"
NEW_KEY = "sk-ant-api03-postgres-replacement-key-2222"


async def _mark_error(account_id: str, connection_id: UUID) -> None:
    store = OAuthConnectionStore()
    row = await store.get(account_id, connection_id)
    assert row is not None and await store.mark_error(row, "rejected") is not None


def test_a_key_replacement_holding_the_marker_makes_the_oauth_start_lose_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = backing._account_id(pg_client)
    name = backing._fresh_name()
    effective = backing._seed(
        pg_client, account_id, name, auth_type="api_key", blob=backing._api_key_blob(OLD_KEY)
    )
    backing._call(pg_client, _mark_error, account_id, effective)
    assert backing._connection(pg_client, account_id, effective).label == name  # api_key keeps it
    generation = backing._marker(pg_client, account_id).generation
    hold = backing._MarkerHold(monkeypatch, holds=lambda i, _kw: i == 0)

    with ThreadPoolExecutor(max_workers=2) as executor:
        setting = executor.submit(
            pg_client.put,
            f"/v1/oauth/connections/{effective}/api-key",
            json={"api_key": NEW_KEY},
        )
        assert hold.held.wait(20), "the key replacement never advanced the marker"
        starting = executor.submit(
            pg_client.post, f"/v1/auth/{PROVIDER}/profiles", json={"name": name}
        )
        assert hold.attempted.wait(20), "the OAuth start never reached its marker advance"
        hold.release.set()
        set_result = setting.result(timeout=30)
        started = starting.result(timeout=30)

    assert set_result.status_code == 200, set_result.text
    assert started.status_code == 409, started.text
    assert started.json()["detail"]["code"] == "connection_conflict"
    # The loser's whole transaction rolled back: the errored row was NOT retired, no new row.
    row = backing._connection(pg_client, account_id, effective)
    assert (row.status, row.auth_type, row.label) == ("active", "api_key", name)
    rows = backing._call(pg_client, OAuthConnectionStore().list, account_id, provider=PROVIDER)
    assert [r.id for r in rows] == [effective]
    pair = backing._marker(pg_client, account_id)
    assert (pair.effective_connection_id, pair.generation) == (effective, generation + 1)
    blob = backing._profile_blob(pg_client, account_id, name)
    assert blob is not None and json.loads(blob)["api_key"] == NEW_KEY


async def _two_rows_at_one_address(app: FastAPI, account_id: str, name: str) -> tuple[UUID, UUID]:
    """Pre-fix data: two live rows of an unmigrated pair sharing one Profile-addressed blob."""
    await app.state.credential_store.write(
        credential_service_for(credential_name_for(account_id, name)),
        "default",
        backing._api_key_blob(OLD_KEY),
    )
    store = OAuthConnectionStore()
    ids: list[UUID] = []
    for label in (f"{name}-a", f"{name}-b"):
        row = await store.create_pending(
            account_id=account_id,
            provider=PROVIDER,
            label=label,
            connection_id=uuid4(),
            credential_provider=PROVIDER,
            credential_locator=credential_locator_for(PROVIDER, account_id, name),
        )
        ids.append((await store.complete(row, label=label, identity=None)).id)
    return ids[0], ids[1]


async def _lock_waiters() -> int:
    rows = await connections.get("default").execute_query_dict(
        "SELECT count(*) AS n FROM pg_stat_activity"
        " WHERE wait_event_type = 'Lock' AND datname = current_database()"
    )
    return int(rows[0]["n"])


@pytest.mark.parametrize("lower_first", [True, False], ids=["lower-id-first", "higher-id-first"])
def test_two_concurrent_deletes_of_rows_sharing_a_blob_leave_no_orphan_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch, lower_first: bool
) -> None:
    account_id = backing._account_id(pg_client)
    name = backing._fresh_name()
    backing._call(pg_client, backing._reset_pair, backing._app(pg_client), account_id)
    low, high = sorted(
        backing._call(
            pg_client, _two_rows_at_one_address, backing._app(pg_client), account_id, name
        )
    )
    first, second = (low, high) if lower_first else (high, low)
    held, attempted, release = threading.Event(), threading.Event(), threading.Event()
    real = oauth_routes.credential_has_other_owner
    calls = {"n": 0}

    async def check(app: Any, connection: Any) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            # The first delete has decided while the other row was still live — and holds its txn.
            result = await real(app, connection)
            held.set()
            if not await asyncio.to_thread(release.wait, 20):
                raise TimeoutError("the first delete was never released")
            return result
        attempted.set()
        return await real(app, connection)

    monkeypatch.setattr(oauth_routes, "credential_has_other_owner", check)

    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(pg_client.delete, f"/v1/oauth/connections/{first}")
        assert held.wait(20), "the first delete never reached its owner check"
        two = executor.submit(pg_client.delete, f"/v1/oauth/connections/{second}")
        # WHY either signal: unserialized, the second delete reaches its own check at once; with
        # the id-ordered row locks it is parked on a PostgreSQL row lock (before or inside the
        # check, by id order). Both mean the two deletes truly overlap before the first commits.
        deadline = time.monotonic() + 20
        while not attempted.is_set() and backing._call(pg_client, _lock_waiters) == 0:
            assert time.monotonic() < deadline, "the second delete never overlapped the first"
            time.sleep(0.05)
        release.set()
        results = (one.result(timeout=30), two.result(timeout=30))

    assert [r.status_code for r in results] == [204, 204], [r.text for r in results]
    for row_id in (first, second):
        assert backing._connection(pg_client, account_id, row_id).status == "revoked"
    # INVARIANT: the blob goes with its LAST live addresser — two deletes that each saw the other
    # alive must not both keep it, or the credential outlives every row that could serve it.
    assert backing._profile_blob(pg_client, account_id, name) is None
