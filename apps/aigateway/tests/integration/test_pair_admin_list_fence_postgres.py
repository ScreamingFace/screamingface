"""PostgreSQL generation fence for the G1 pair inventory."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
import test_provider_access_backing_postgres as backing
from fastapi.testclient import TestClient

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
    first_profiles_read = threading.Event()
    release = threading.Event()
    profile_reads = 0
    real_list = app.state.profile_index.list

    async def held_list(*args: Any, **kwargs: Any):
        nonlocal profile_reads
        profiles = await real_list(*args, **kwargs)
        profile_reads += 1
        if profile_reads == 1:
            first_profiles_read.set()
            if not await asyncio.to_thread(release.wait, 20):
                raise TimeoutError("the marker writer was not released")
        return profiles

    monkeypatch.setattr(app.state.profile_index, "list", held_list)

    def read_inventory() -> PairInventory:
        return backing._call(pg_client, pair_inventory, app, account_id)

    def advance_marker() -> None:
        assert first_profiles_read.wait(20), "LIST did not reach the held candidate read"
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
    assert profile_reads == 2
    assert backing._marker(pg_client, account_id).generation == 1
