from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import Baseline, Benchmark
from scoreboard.scores.schemas import BaselineImportRow


def row(**changes):
    return BaselineImportRow(
        **{
            "benchmark_id": "history",
            "model_name": "Model",
            "source": "paper",
            "score": 0.8,
            "source_url": "https://example.org/results",
            "metric_name": "accuracy",
            "attached_by": "private-editor",
            **changes,
        }
    )


async def read_history(baseline_id, *, board="history", query=""):
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(
            f"/v1/leaderboard/{board}/external-results/{baseline_id}/history{query}"
        )


@pytest.mark.asyncio
async def test_changed_import_keeps_previous_values_and_noop_does_not_add_revision(tortoise_db):
    await Benchmark.create(id="history", display_name="History")
    store = BaselineStore()
    first = await store.import_baseline(row())
    assert first.observation_revision == 1
    assert first.observation_updated_at is None
    second = await store.import_baseline(
        row(score=0.82, source_url="https://example.org/correction")
    )
    repeat = await store.import_baseline(
        row(score=0.82, source_url="https://example.org/correction")
    )
    assert repeat.id == second.id == first.id
    assert repeat.observation_revision == 2
    assert repeat.observation_updated_at == second.observation_updated_at
    assert repeat.last_imported_at is not None and second.last_imported_at is not None
    assert second.observation_updated_at is not None
    assert repeat.last_imported_at >= second.last_imported_at
    response = await read_history(first.id)
    assert response.status_code == 200
    data = response.json()
    assert data["current_revision"] == 2
    assert data["next_before"] is None
    assert [(v["revision"], v["score"], v["source_url"]) for v in data["versions"]] == [
        (2, 0.82, "https://example.org/correction"),
        (1, 0.8, "https://example.org/results"),
    ]
    assert data["versions"][0]["recorded_at"] == second.observation_updated_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert all("attached_by" not in v for v in data["versions"])
    assert "private-editor" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"metadata": {"comparison_note": "Corrected prompt information"}},
        {"metric_name": "f1"},
        {"source_url": None},
        {"observed_at": datetime(2026, 11, 1, tzinfo=UTC)},
        {"attached_by": "another-private-editor"},
    ],
)
async def test_provenance_changes_are_versioned_even_when_score_is_unchanged(tortoise_db, changes):
    await Benchmark.create(id="history", display_name="History")
    store = BaselineStore()
    first = await store.import_baseline(row())
    changed = await store.import_baseline(row(**changes))
    assert changed.observation_revision == 2
    data = (await read_history(first.id)).json()
    assert [v["score"] for v in data["versions"]] == [0.8, 0.8]
    assert data["versions"][1]["metadata"] is None
    assert data["versions"][1]["observed_at"] is None


@pytest.mark.asyncio
async def test_legacy_first_edit_preserves_state_without_inventing_its_date(tortoise_db):
    await Benchmark.create(id="history", display_name="History")
    legacy = await Baseline.create(**row().model_dump())
    changed = await BaselineStore().import_baseline(
        row(score=0.82, metric_name=None, attached_by=None)
    )
    assert changed.id == legacy.id
    data = (await read_history(legacy.id)).json()
    assert [(v["revision"], v["score"]) for v in data["versions"]] == [(2, 0.82), (1, 0.8)]
    assert data["versions"][1]["recorded_at"] is None
    assert data["versions"][1]["metric_name"] == "accuracy"
    assert data["versions"][0]["metric_name"] is None


@pytest.mark.asyncio
async def test_failed_batch_rolls_back_history_as_well_as_current_result(tortoise_db):
    await Benchmark.create(id="history", display_name="History")
    store = BaselineStore()
    first = await store.import_baseline(row())
    with pytest.raises(ValueError):
        await store.import_many([row(score=0.82), row(benchmark_id="missing")])
    [current] = await store.list_baselines("history")
    assert current.score == 0.8
    assert current.observation_revision == 1
    assert current.last_imported_at == first.last_imported_at
    assert len((await read_history(first.id)).json()["versions"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["public", "private"])
async def test_history_is_scoped_paginated_and_never_exposes_attribution(tortoise_db, visibility):
    await Benchmark.create(id="history", display_name="History", visibility=visibility)
    await Benchmark.create(id="other", display_name="Other")
    versions = await BaselineStore().import_many([row(score=0.7), row(score=0.8), row(score=0.9)])
    first = (await read_history(versions[0].id, query="?limit=2")).json()
    assert [v["revision"] for v in first["versions"]] == [3, 2]
    assert first["next_before"] == 2
    second = (await read_history(versions[0].id, query="?limit=2&before=2")).json()
    assert [v["revision"] for v in second["versions"]] == [1]
    assert second["next_before"] is None
    assert all("attached_by" not in v and "ranking_eligible" not in v for v in first["versions"])
    assert (await read_history(versions[0].id, board="other")).status_code == 404
    assert (await read_history(versions[0].id, query="?limit=0")).status_code == 422
    assert (await read_history(versions[0].id, query="?before=0")).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_unchanged_legacy_refresh_and_openness_edit_do_not_create_history(
    tortoise_db, legacy
):
    await Benchmark.create(id="history", display_name="History")
    if legacy:
        first = await Baseline.create(**row().model_dump())
    else:
        first = await BaselineStore().import_baseline(row())
    await Baseline.filter(id=first.id).update(openness_override="open")
    refreshed = await BaselineStore().import_baseline(row())
    assert refreshed.observation_revision == 1
    assert refreshed.observation_updated_at is None
    assert refreshed.openness_override == "open"
    assert len((await read_history(first.id)).json()["versions"]) == 1


@pytest.mark.asyncio
async def test_same_observation_in_another_timezone_does_not_create_version(tortoise_db):
    from datetime import timedelta, timezone

    await Benchmark.create(id="history", display_name="History")
    instant = datetime(2026, 11, 1, tzinfo=UTC)
    first = await BaselineStore().import_baseline(row(observed_at=instant))
    repeated = await BaselineStore().import_baseline(
        row(observed_at=instant.astimezone(timezone(timedelta(hours=2))))
    )
    assert first.observation_revision == repeated.observation_revision == 1


@pytest.mark.asyncio
async def test_history_write_failure_rolls_back_current_update(tortoise_db, monkeypatch):
    from unittest.mock import AsyncMock

    from scoreboard.scores.models import BaselineRevision

    await Benchmark.create(id="history", display_name="History")
    first = await BaselineStore().import_baseline(row())
    monkeypatch.setattr(
        BaselineRevision, "create", AsyncMock(side_effect=RuntimeError("storage failed"))
    )
    with pytest.raises(RuntimeError):
        await BaselineStore().import_baseline(row(score=0.9))
    stored = await Baseline.get(id=first.id)
    assert stored.score == 0.8
    assert stored.observation_revision == 1
    assert stored.last_imported_at == first.last_imported_at


@pytest.mark.asyncio
async def test_metadata_key_order_is_noop_but_boolean_to_number_is_a_change(tortoise_db):
    await Benchmark.create(id="history", display_name="History")
    store = BaselineStore()
    first = await store.import_baseline(row(metadata={"flag": True, "note": "same"}))
    reordered = await store.import_baseline(row(metadata={"note": "same", "flag": True}))
    assert first.observation_revision == reordered.observation_revision == 1
    changed = await store.import_baseline(row(metadata={"note": "same", "flag": 1}))
    assert changed.observation_revision == 2
    versions = (await read_history(first.id)).json()["versions"]
    assert type(versions[0]["metadata"]["flag"]) is int
    assert versions[1]["metadata"]["flag"] is True
