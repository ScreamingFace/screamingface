"""PostgreSQL race of a G0 error mark against an in-place key replacement (OME-1497, part 3).

# FEATURE: OME-1138 D18, G0 (contract §5.3) — an error mark checks the pair generation under the
# marker row lock and never advances it.
# INVARIANT: on PostgreSQL (READ COMMITTED) a mark that waits on the marker row held by a key
# replacement re-reads the committed generation after the wait and loses: the replaced key stays
# `active`. SQLite has no row locks, so only this lane proves the wait-then-recheck.
# AIDEV-NOTE: fixtures and helpers are bound from the S2'c module; run with `AIGW_TEST_PG=1`.
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_provider_access_backing_postgres as backing
from fastapi.testclient import TestClient

import aigateway.routes.oauth_connections as routes
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.provider_access import PairAuthorityStore
from aigateway.core.provider_access.models import ProviderCredentialSlot
from aigateway.core.provider_access.writer_floor import mark_error_checked

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client

PROVIDER = backing.PROVIDER
OLD_KEY = "sk-ant-api03-postgres-mark-old-1357"
NEW_KEY = "sk-ant-api03-postgres-mark-new-2468"


def test_an_error_mark_waiting_on_a_key_replacement_loses_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = backing._account_id(pg_client)
    backing._call(pg_client, backing._reset_pair, backing._app(pg_client), account_id)
    created = pg_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": PROVIDER, "label": backing._fresh_name(), "api_key": OLD_KEY},
    )
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]
    # What the failing request observed before its provider call.
    observed = backing._call(pg_client, PairAuthorityStore().read, account_id, PROVIDER)
    connection = backing._connection(pg_client, account_id, connection_id)
    hold = backing._MarkerHold(monkeypatch, holds=lambda index, _kw: index == 0)

    def replace() -> object:
        return pg_client.put(
            f"/v1/oauth/connections/{connection_id}/api-key", json={"api_key": NEW_KEY}
        )

    def mark() -> None:
        backing._call(
            pg_client,
            mark_error_checked,
            OAuthConnectionStore(),
            connection,
            "revoked",
            observed=observed,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        replacing = executor.submit(replace)
        assert hold.held.wait(20), "the key replacement never claimed the pair"
        marking = executor.submit(mark)
        time.sleep(0.5)
        assert not marking.done(), "the mark did not wait on the marker row"
        hold.release.set()
        replaced = replacing.result(timeout=30)
        marking.result(timeout=30)

    assert getattr(replaced, "status_code", None) == 200, getattr(replaced, "text", replaced)
    row = backing._connection(pg_client, account_id, connection_id)
    assert row.status == "active"
    assert backing._marker(pg_client, account_id).generation == observed.generation + 1


def test_an_error_mark_on_an_unmarked_pair_loses_to_a_first_claim_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: an unmarked pair has no row to lock; the first claim's uncommitted marker hides from
    # the check while its key write holds the Connection row. The mark waits on that row and must
    # still lose once the replacement commits (the re-check after the mark).
    account_id = backing._account_id(pg_client)
    backing._call(pg_client, backing._reset_pair, backing._app(pg_client), account_id)
    created = pg_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": PROVIDER, "label": backing._fresh_name(), "api_key": OLD_KEY},
    )
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]

    async def unmark() -> None:
        # A Connection from before G0: its pair has no marker yet.
        await ProviderCredentialSlot.filter(account_id=account_id, provider=PROVIDER).delete()

    backing._call(pg_client, unmark)
    observed = backing._call(pg_client, PairAuthorityStore().read, account_id, PROVIDER)
    assert observed.generation == 0
    connection = backing._connection(pg_client, account_id, connection_id)

    held = threading.Event()
    release = threading.Event()
    persist = routes._persist_api_key_credentials

    async def held_persist(strategy: object, api_key: str) -> object:
        held.set()  # the marker is inserted and the row reactivated, neither committed
        await asyncio.to_thread(release.wait, 20)
        return await persist(strategy, api_key)

    monkeypatch.setattr(routes, "_persist_api_key_credentials", held_persist)

    def replace() -> object:
        return pg_client.put(
            f"/v1/oauth/connections/{connection_id}/api-key", json={"api_key": NEW_KEY}
        )

    def mark() -> None:
        backing._call(
            pg_client,
            mark_error_checked,
            OAuthConnectionStore(),
            connection,
            "revoked",
            observed=observed,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        replacing = executor.submit(replace)
        assert held.wait(20), "the key replacement never reached its key write"
        marking = executor.submit(mark)
        time.sleep(0.5)
        assert not marking.done(), "the mark did not wait on the Connection row"
        release.set()
        replaced = replacing.result(timeout=30)
        marking.result(timeout=30)

    assert getattr(replaced, "status_code", None) == 200, getattr(replaced, "text", replaced)
    assert backing._connection(pg_client, account_id, connection_id).status == "active"
    assert backing._marker(pg_client, account_id).generation == 1
