from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from scoreboard.config import Settings
from scoreboard.import_baselines import load_baselines_json, main
from scoreboard.main import create_app
from scoreboard.scores import baseline_store
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import Baseline, Benchmark
from scoreboard.scores.schemas import BaselineImportRow


def _payload(**overrides: Any) -> dict[str, Any]:
    return {
        "benchmark_id": "review",
        "model_name": "Model",
        "score": 0.75,
        "source": "paper",
        **overrides,
    }


@pytest.mark.asyncio
async def test_first_import_timestamp_never_precedes_creation(tortoise_db: None) -> None:
    await Benchmark.create(id="review", display_name="Review")
    result = await BaselineStore().import_baseline(BaselineImportRow(**_payload()))
    assert result.last_imported_at is not None
    assert result.last_imported_at >= result.imported_at
    stored = await Baseline.get(id=result.id)
    assert stored.last_imported_at == result.last_imported_at


@pytest.mark.asyncio
async def test_replacement_timestamp_survives_clock_moving_backwards(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await Benchmark.create(id="review", display_name="Review")
    store = BaselineStore()
    first = await store.import_baseline(BaselineImportRow(**_payload()))

    class EarlierClock:
        @staticmethod
        def now(tz: object) -> datetime:
            return first.imported_at - timedelta(days=1)

    monkeypatch.setattr(baseline_store, "datetime", EarlierClock)
    second = await store.import_baseline(BaselineImportRow(**_payload(score=0.8)))
    assert second.id == first.id
    assert second.score == 0.8
    assert second.last_imported_at is not None and first.last_imported_at is not None
    assert second.last_imported_at >= first.last_imported_at
    assert second.last_imported_at >= second.imported_at


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("SCOREBOARD_TEST_DATABASE_URL"), reason="requires PostgreSQL")
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("batch", [False, True])
async def test_overlapping_imports_stamp_in_write_order(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch, existing: bool, batch: bool
) -> None:
    await Benchmark.create(id="review", display_name="Review")
    store = BaselineStore()
    if existing:
        await store.import_baseline(BaselineImportRow(**_payload()))
    entered, resume = asyncio.Event(), asyncio.Event()
    original = Baseline.update_or_create
    times = [datetime.now(UTC) + timedelta(seconds=1)]

    class Clock:
        @staticmethod
        def now(tz: object) -> datetime:
            return times[0]

    async def delayed(cls: type[Baseline], **kwargs: Any) -> tuple[Baseline, bool]:
        if kwargs["defaults"]["score"] == 0.81:
            entered.set()
            await asyncio.wait_for(resume.wait(), timeout=10)
        return await original(**kwargs)

    async def run(score: float):
        row = BaselineImportRow(**_payload(score=score))
        return (await store.import_many([row]))[0] if batch else await store.import_baseline(row)

    monkeypatch.setattr(baseline_store, "datetime", Clock)
    monkeypatch.setattr(Baseline, "update_or_create", classmethod(delayed))
    first_task = asyncio.create_task(run(0.81))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        times[0] += timedelta(seconds=1)
        completed = await asyncio.wait_for(run(0.82), timeout=10)
    finally:
        resume.set()
    last = await asyncio.wait_for(first_task, timeout=10)
    _assert_ordered_replacements(await store.list_baselines("review"), completed, last)


def _assert_ordered_replacements(rows, completed, last) -> None:
    [stored] = rows
    assert stored.id == completed.id == last.id
    assert stored.score == 0.81
    assert stored.last_imported_at == last.last_imported_at
    assert stored.last_imported_at is not None and completed.last_imported_at is not None
    assert stored.last_imported_at >= completed.last_imported_at
    assert stored.last_imported_at >= stored.imported_at


@pytest.mark.parametrize("field", ["metric_name", "attached_by"])
@pytest.mark.parametrize("character", ["\x85", "\u200b", "\u202e", "\u2066", "\ud800", "\udfff"])
def test_provenance_rejects_unicode_controls_and_surrogates(field: str, character: str) -> None:
    with pytest.raises(ValidationError) as caught:
        BaselineImportRow(**_payload(**{field: f"before{character}after"}))
    assert caught.value.errors()[0]["loc"] == (field,)


def test_provenance_preserves_readable_international_text() -> None:
    row = BaselineImportRow(**_payload(metric_name=" Précision 精度 ", attached_by=" Željko 李 "))
    assert row.metric_name == "Précision 精度"
    assert row.attached_by == "Željko 李"


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["public", "private"])
async def test_read_api_excludes_legacy_metric_with_display_controls(
    tortoise_db: None, visibility: str
) -> None:
    await Benchmark.create(id="review", display_name="Review", visibility=visibility)
    await BaselineStore().import_baseline(BaselineImportRow(**_payload(metric_name="accuracy")))
    await Baseline.create(**_payload(model_name="Unsafe", metric_name="acc\u202euracy"))
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/leaderboard/review")
    assert response.status_code == 200
    assert [row["metric_name"] for row in response.json()["baselines"]] == ["accuracy"]


def test_cli_errors_do_not_echo_private_attribution(capsys: pytest.CaptureFixture[str]) -> None:
    raw = json.dumps([_payload(attached_by="private-operator-name\nsecond-line")])
    with pytest.raises(SystemExit) as caught:
        main(["--baselines-json", raw])
    assert caught.value.code == 2
    output = capsys.readouterr()
    assert "private-operator-name" not in output.err
    assert "second-line" not in output.err
    assert "attached_by" in output.err
    assert "invalid baseline import payload" in output.err
    assert output.out == ""


def test_loader_errors_do_not_expose_rejected_values_or_chained_validation() -> None:
    raw = json.dumps([_payload(attached_by="private-operator-name\nsecond-line")])
    with pytest.raises(ValueError) as caught:
        load_baselines_json(raw)
    assert "private-operator-name" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
