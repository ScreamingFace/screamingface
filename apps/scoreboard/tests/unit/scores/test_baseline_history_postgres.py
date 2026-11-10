"""History keeps every committed observation when importers overlap."""

from __future__ import annotations

import asyncio
import os

import pytest

from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import Baseline, BaselineRevision, Benchmark
from tests.unit.scores.test_baseline_history import row

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
