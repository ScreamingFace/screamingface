"""With `SCOREBOARD_CLUSTERING_ENABLED` off the E14 request fields are ignored, and only logged.

FEATURE: OME-1307 (E14). A newer Client can talk to an older board or to one with the flag off:
the fields are accepted (never a 422), the run is stored by the legacy path, and the only trace is
an INFO line with the field NAMES. The receipt itself is never logged.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, ReportedResult
from tests.unit.submissions._receipts import post_score

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def flag_off_client(tortoise_db: None) -> AsyncGenerator[AsyncClient, None]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    await Benchmark.create(id="pub", display_name="Pub")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_e14_fields_are_ignored_and_logged_by_name_only(
    flag_off_client: AsyncClient,
    sign_receipt: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    receipt = sign_receipt()
    caplog.set_level(logging.INFO, logger="scoreboard.routes.scores")

    response = await post_score(
        flag_off_client, user=None, receipt=receipt, revision_of="kevins-best"
    )

    assert response.status_code == 201
    assert "reported_result" not in response.json()
    assert await ReportedResult.all().count() == 0
    lines = [r.getMessage() for r in caplog.records if "e14_fields_ignored" in r.getMessage()]
    assert lines == ["e14_fields_ignored fields=cache_version_receipt,revision_of,trace_id"]
    assert receipt not in caplog.text


async def test_nothing_is_logged_when_no_e14_field_is_sent(
    flag_off_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="scoreboard.routes.scores")

    response = await post_score(flag_off_client, user=None, trace_id=None)

    assert response.status_code == 201
    assert "e14_fields_ignored" not in caplog.text
