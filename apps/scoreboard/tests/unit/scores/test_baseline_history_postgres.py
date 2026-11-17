"""History keeps every committed observation when importers overlap."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest
from tortoise.transactions import in_transaction

from scoreboard.config import Settings
from scoreboard.db import DEFAULT_CONNECTION
from scoreboard.main import create_app
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import Baseline, BaselineRevision, Benchmark
from tests.unit.scores.test_baseline_history import read_history, row

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not os.getenv("SCOREBOARD_TEST_DATABASE_URL"), reason="requires PostgreSQL"),
]


@pytest.mark.parametrize("initial", ["absent", "legacy", "versioned"])
@pytest.mark.parametrize("same", [False, True])
async def test_overlapping_imports_preserve_all_changes(tortoise_db, initial, same):
    await Benchmark.create(id="history", display_name="History")
    store = BaselineStore()
    if initial == "legacy":
        await Baseline.create(**row().model_dump())
    elif initial == "versioned":
        await store.import_baseline(row())
    ready = asyncio.Event()

    async def write(score):
        await ready.wait()
        return await store.import_baseline(row(score=score))

    tasks = [asyncio.create_task(write(0.81)), asyncio.create_task(write(0.81 if same else 0.82))]
    ready.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    assert results[0].id == results[1].id
    versions = await BaselineRevision.filter(baseline_id=results[0].id).order_by("revision")
    expected = ([0.8] if initial != "absent" else []) + ([0.81] if same else [0.81, 0.82])
    assert sorted(v.observation["score"] for v in versions) == sorted(expected)
    assert [v.revision for v in versions] == list(range(1, len(expected) + 1))
    stored = await Baseline.get(id=results[0].id)
    assert stored.score == versions[-1].observation["score"]
    assert stored.observation_revision == versions[-1].revision


async def test_history_and_board_reads_do_not_wait_for_uncommitted_import(tortoise_db):
    await Benchmark.create(id="history", display_name="History")
    store = BaselineStore()
    baseline = await store.import_baseline(row())
    written, release = asyncio.Event(), asyncio.Event()

    async def importer():
        async with in_transaction(connection_name=DEFAULT_CONNECTION) as connection:
            await store.import_baseline(row(score=0.9), using_db=connection)
            written.set()
            await release.wait()

    # WHY: a separate task prevents the HTTP reads inheriting the import transaction.
    task = asyncio.create_task(importer())
    try:
        await asyncio.wait_for(written.wait(), timeout=5)
        app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(read_history(baseline.id) for _ in range(4)),
                    client.get("/v1/leaderboard/history"),
                ),
                timeout=2,
            )
        assert all(response.status_code == 200 for response in results)
        for response in results[:-1]:
            data = response.json()
            assert data["current_revision"] == 1
            assert [(v["revision"], v["score"]) for v in data["versions"]] == [(1, 0.8)]
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=5)
    committed = (await read_history(baseline.id)).json()
    assert committed["current_revision"] == 2
    assert [v["score"] for v in committed["versions"]] == [0.9, 0.8]


@pytest.mark.parametrize("value", [1e16, 1e23, -1e23, {"nested": [1e16, True]}])
async def test_jsonb_number_representation_does_not_create_a_revision(tortoise_db, value):
    await Benchmark.create(id="history", display_name="History")
    store = BaselineStore()
    first = await store.import_baseline(row(metadata={"x": value}))
    repeated = await store.import_baseline(row(metadata={"x": value}))
    assert repeated.id == first.id
    assert repeated.observation_revision == 1
    assert await BaselineRevision.filter(baseline_id=first.id).count() == 1
