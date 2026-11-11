import asyncio
from datetime import timedelta

import pytest
from tortoise import connections

from scoreboard.scores.models import SourceHealth
from scoreboard.scores.source_health import record_check
from tests.unit.scores.test_source_health import NOW, URL


@pytest.mark.asyncio
async def test_overlapping_first_checks_retain_latest_attempt_and_success(tortoise_db):
    if connections.get("default").capabilities.dialect != "postgres":
        pytest.skip("row-lock concurrency requires PostgreSQL")
    outcomes = [
        (False, NOW + timedelta(seconds=4)),
        (True, NOW + timedelta(seconds=2)),
        (False, NOW),
        (True, NOW + timedelta(seconds=1)),
    ]
    await asyncio.gather(
        *(record_check(URL, available=ok, checked_at=when) for ok, when in outcomes)
    )
    [row] = await SourceHealth.all()
    assert row.available is False
    assert row.checked_at == NOW + timedelta(seconds=4)
    assert row.last_available_at == NOW + timedelta(seconds=2)
