"""PostgreSQL generation fence for the G1 pair inventory."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
import test_provider_access_backing_postgres as backing
from fastapi.testclient import TestClient

from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.core.provider_access import PairAuthorityStore, PairInventory, pair_inventory

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client


def test_list_retries_when_a_pair_generation_commits_between_candidate_reads(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = backing._account_id(pg_client)
    app = backing._app(pg_client)
    backing._call(pg_client, backing._reset_pair, app, account_id)
    first_candidate_read = threading.Event()
    release = threading.Event()
    candidate_reads = 0
    real_list = OAuthConnectionStore.list

    # WHY the Connection list: LIST reads no Profile document (OME-1209 E4a), so the pair's live
    # Connections are the candidate read the generation fence brackets.
    async def held_list(self: OAuthConnectionStore, *args: Any, **kwargs: Any):
        nonlocal candidate_reads
        connections = await real_list(self, *args, **kwargs)
        candidate_reads += 1
        if candidate_reads == 1:
            first_candidate_read.set()
            if not await asyncio.to_thread(release.wait, 20):
                raise TimeoutError("the marker writer was not released")
        return connections

    monkeypatch.setattr(OAuthConnectionStore, "list", held_list)

    def read_inventory() -> PairInventory:
        return backing._call(pg_client, pair_inventory, app, account_id)

    def advance_marker() -> None:
        assert first_candidate_read.wait(20), "LIST did not reach the held candidate read"
        try:
            backing._call(
                pg_client,
                PairAuthorityStore().advance,
                account_id,
                backing.PROVIDER,
                expected_generation=0,
                migration_state="none",
            )
        finally:
            release.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        listing = executor.submit(read_inventory)
        writer = executor.submit(advance_marker)
        writer.result(timeout=30)
        inventory = listing.result(timeout=30)

    assert inventory == PairInventory(credentials=(), conflicts=())
    assert candidate_reads == 2
    assert backing._marker(pg_client, account_id).generation == 1
