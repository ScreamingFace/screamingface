from datetime import UTC, datetime, timedelta

import httpx
import pytest

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import BaselineRevision
from scoreboard.scores.source_health import record_check
from tests.unit.scores.test_baseline_comparison import BOARD, _board, _row

NOW = datetime(2026, 11, 11, 10, tzinfo=UTC)
URL = "https://example.org/results"


@pytest.mark.asyncio
async def test_failure_recovery_keeps_score_rank_and_history(tortoise_db):
    await _board()
    original = await BaselineStore().import_baseline(_row(source_url=URL))
    await record_check(URL, available=True, checked_at=NOW)
    await record_check(URL, available=False, checked_at=NOW + timedelta(hours=1))
    [row] = await BaselineStore().list_baselines(BOARD)
    assert row.source_health is not None
    assert row.source_health.available is False
    assert row.source_health is not None
    assert row.source_health.last_available_at == NOW
    assert row.source_health is not None
    assert row.source_health.checked_at == NOW + timedelta(hours=1)
    assert row.ranking_eligible is True
    assert (row.id, row.score, row.source_url) == (original.id, original.score, URL)
    assert await BaselineRevision.all().count() == 1
    await record_check(URL, available=True, checked_at=NOW + timedelta(hours=2))
    [row] = await BaselineStore().list_baselines(BOARD)
    assert row.source_health is not None
    assert row.source_health.available is True
    assert row.source_health is not None
    assert row.source_health.last_available_at == NOW + timedelta(hours=2)
    await BaselineStore().import_baseline(_row(source_url=URL))
    assert await BaselineRevision.all().count() == 1


@pytest.mark.asyncio
async def test_first_failure_does_not_invent_last_success(tortoise_db):
    await _board()
    await BaselineStore().import_baseline(_row(source_url=URL))
    [row] = await BaselineStore().list_baselines(BOARD)
    assert row.source_health is None
    await record_check(URL, available=False, checked_at=NOW)
    [row] = await BaselineStore().list_baselines(BOARD)
    assert row.source_health is not None
    assert row.source_health.last_available_at is None


@pytest.mark.asyncio
async def test_changed_url_does_not_inherit_old_status(tortoise_db):
    await _board()
    await BaselineStore().import_baseline(_row(source_url=URL))
    await record_check(URL, available=False, checked_at=NOW)
    await BaselineStore().import_baseline(_row(source_url=URL + "/new"))
    [row] = await BaselineStore().list_baselines(BOARD)
    assert row.source_health is None


@pytest.mark.asyncio
async def test_late_result_cannot_replace_newer_status(tortoise_db):
    await record_check(URL, available=False, checked_at=NOW + timedelta(hours=1))
    await record_check(URL, available=True, checked_at=NOW)
    await _board()
    await BaselineStore().import_baseline(_row(source_url=URL))
    [row] = await BaselineStore().list_baselines(BOARD)
    assert row.source_health is not None
    assert row.source_health.available is False
    assert row.source_health is not None
    assert row.source_health.checked_at == NOW + timedelta(hours=1)
    assert row.source_health is not None
    assert row.source_health.last_available_at == NOW
    await record_check(URL, available=False, checked_at=NOW - timedelta(hours=1))
    [row] = await BaselineStore().list_baselines(BOARD)
    assert row.source_health is not None
    assert row.source_health.last_available_at == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["public", "private"])
async def test_health_api_is_explicit_and_source_checks_are_not_import_fields(
    tortoise_db, visibility
):
    await _board(visibility=visibility)
    await BaselineStore().import_baseline(_row(source_url=URL, attached_by="private@example.org"))
    await record_check(URL, available=False, checked_at=NOW)
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get(f"/v1/leaderboard/{BOARD}")
    health = response.json()["baselines"][0]["source_health"]
    assert health == {
        "available": False,
        "checked_at": "2026-11-11T10:00:00Z",
        "last_available_at": None,
    }
    assert "private@example.org" not in response.text
    with pytest.raises(ValueError):
        _row(source_health=health)
