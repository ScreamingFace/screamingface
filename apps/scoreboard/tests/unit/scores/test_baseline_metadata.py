from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from scoreboard.config import Settings
from scoreboard.import_baselines import import_baselines, load_baselines_json
from scoreboard.main import create_app
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import Baseline, Benchmark
from scoreboard.scores.schemas import BaselineImportRow


def _payload(**overrides: Any) -> dict[str, Any]:
    return {
        "benchmark_id": "demo",
        "model_name": "Example model",
        "score": 0.75,
        "source": "paper-table",
        "source_url": "https://example.org/paper/table",
        "metric_name": "accuracy",
        "observed_at": "2026-11-02T14:00:00+02:00",
        "attached_by": "public-handle",
        "metadata": {"comparison_note": "Same questions; prompts differ."},
        **overrides,
    }


def _load(**overrides: Any) -> BaselineImportRow:
    return load_baselines_json(json.dumps([_payload(**overrides)]))[0]


def test_json_import_accepts_named_provenance_and_trims_text() -> None:
    row = _load(metric_name=" accuracy ", attached_by=" public-handle ")
    assert row.metric_name == "accuracy"
    assert row.attached_by == "public-handle"
    assert row.observed_at == datetime(2026, 11, 2, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("metric_name", ""),
        ("metric_name", "   "),
        ("metric_name", "x" * 129),
        ("metric_name", "acc\x00uracy"),
        ("attached_by", ""),
        ("attached_by", "\t "),
        ("attached_by", "x" * 256),
        ("attached_by", "first\nsecond"),
        ("observed_at", "2026-11-02T12:00:00"),
        ("observed_at", "2026-11-02"),
        ("observed_at", "not-a-date"),
        ("last_imported_at", "2026-11-02T12:00:00Z"),
    ],
)
def test_invalid_provenance_is_rejected(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        _load(**{field: value})


def test_provenance_text_accepts_exact_storage_bounds() -> None:
    row = _load(metric_name="m" * 128, attached_by="a" * 255)
    assert len(row.metric_name or "") == 128
    assert len(row.attached_by or "") == 255


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["public", "private"])
async def test_metadata_round_trips_without_publishing_attribution(
    tortoise_db: None, visibility: str
) -> None:
    await Benchmark.create(id="demo", display_name="Demo", visibility=visibility)
    before = datetime.now(UTC)
    imported = (await import_baselines([_load()]))[0]
    after = datetime.now(UTC)
    stored = (await BaselineStore().list_baselines("demo"))[0]
    assert stored == imported
    assert stored.metric_name == "accuracy"
    assert (await Baseline.get(id=stored.id)).attached_by == "public-handle"
    assert stored.observed_at == datetime(2026, 11, 2, 12, tzinfo=UTC)
    assert stored.last_imported_at is not None
    assert before <= stored.last_imported_at <= after
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/leaderboard/demo")
    assert response.status_code == 200
    baseline = response.json()["baselines"][0]
    assert "attached_by" not in baseline
    assert "attached_by" not in type(stored).model_fields
    for key in ("metric_name", "observed_at", "last_imported_at"):
        assert baseline[key] == stored.model_dump(mode="json")[key]
    assert baseline["source_url"] == "https://example.org/paper/table"
    assert baseline["metadata"] == _payload()["metadata"]


@pytest.mark.asyncio
async def test_legacy_import_and_preexisting_row_leave_unknown_provenance_null(
    tortoise_db: None,
) -> None:
    await Benchmark.create(id="demo", display_name="Demo")
    legacy = {
        key: value
        for key, value in _payload().items()
        if key not in ("metric_name", "observed_at", "attached_by")
    }
    imported = (await import_baselines(load_baselines_json(json.dumps([legacy]))))[0]
    await Baseline.create(benchmark_id="demo", model_name="Old row", score=0.5, source="old")
    old = (await BaselineStore().list_baselines("demo"))[1]
    for row in (imported, old):
        assert row.metric_name is None
        assert row.observed_at is None
        assert (await Baseline.get(id=row.id)).attached_by is None
    assert imported.last_imported_at is not None
    assert old.last_imported_at is None


@pytest.mark.asyncio
async def test_reimport_replaces_observation_without_duplicating_or_redating_first_import(
    tortoise_db: None,
) -> None:
    await Benchmark.create(id="demo", display_name="Demo")
    store = BaselineStore()
    first = await store.import_baseline(_load())
    # WHY: force a past server timestamp without sleeping or depending on clock resolution.
    old_time = datetime.now(UTC) - timedelta(days=1)
    await Baseline.filter(id=first.id).update(last_imported_at=old_time)
    second = await store.import_baseline(
        _load(score=0.8, observed_at="2026-11-03T10:00:00Z", attached_by="another-handle")
    )
    assert second.id == first.id
    assert second.imported_at == first.imported_at
    assert second.last_imported_at is not None and second.last_imported_at > old_time
    assert second.observed_at == datetime(2026, 11, 3, 10, tzinfo=UTC)
    assert (await Baseline.get(id=second.id)).attached_by == "another-handle"
    assert second.score == 0.8
    assert len(await store.list_baselines("demo")) == 1


@pytest.mark.asyncio
async def test_missing_provenance_never_carries_an_old_date_onto_a_replacement_score(
    tortoise_db: None,
) -> None:
    await Benchmark.create(id="demo", display_name="Demo")
    store = BaselineStore()
    await store.import_baseline(_load())
    legacy = {
        key: value
        for key, value in _payload(score=0.9).items()
        if key not in ("metric_name", "observed_at", "attached_by")
    }
    updated = await store.import_baseline(BaselineImportRow.model_validate(legacy))
    assert updated.score == 0.9
    assert updated.metric_name is None
    assert updated.observed_at is None
    assert (await Baseline.get(id=updated.id)).attached_by is None


@pytest.mark.asyncio
async def test_failed_batch_rolls_back_provenance_and_server_import_timestamp(
    tortoise_db: None,
) -> None:
    await Benchmark.create(id="demo", display_name="Demo")
    store = BaselineStore()
    original = await store.import_baseline(_load())
    with pytest.raises(ValueError, match="unknown benchmark_id"):
        await store.import_many(
            [
                _load(score=0.9, attached_by="replacement"),
                _load(benchmark_id="missing"),
            ]
        )
    assert await store.list_baselines("demo") == [original]
    assert (await Baseline.get(id=original.id)).attached_by == "public-handle"


@pytest.mark.asyncio
async def test_import_timestamp_does_not_change_on_an_unrelated_classification_edit(
    tortoise_db: None,
) -> None:
    await Benchmark.create(id="demo", display_name="Demo")
    store = BaselineStore()
    imported = await store.import_baseline(_load())
    baseline = await Baseline.get(id=imported.id)
    baseline.openness_override = "open"
    await baseline.save()
    edited = (await store.list_baselines("demo"))[0]
    assert edited.last_imported_at == imported.last_imported_at
    assert edited.observed_at == imported.observed_at
    assert edited.openness_override == "open"
