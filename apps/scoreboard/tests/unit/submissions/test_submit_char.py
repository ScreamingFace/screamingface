"""SC-1, SC-2 (characterization) — what the legacy path does must stay true with the flag on.

FEATURE: OME-1307 (E14). Both rows are parametrized over `clustering_enabled`. With the flag off
they pass at once (they pin today's behavior). With the flag on they prove the clustered path keeps
the same contract. The `disabled` auth mode is the dev/local fallback (D5), so it is the natural
home of these two legacy rows.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark
from tests.unit.submissions._receipts import ANA, payload

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(params=[False, True], ids=["legacy", "clustered"])
async def disabled_client(
    request: pytest.FixtureRequest, tortoise_db: None, partial_unique_indexes: None
) -> AsyncGenerator[AsyncClient, None]:
    settings = Settings(
        database_url="sqlite://:memory:", cors_origins=[], clustering_enabled=request.param
    )
    app = create_app(settings)
    await Benchmark.create(id="pub", display_name="Pub")
    await Benchmark.create(id="priv", display_name="Priv", visibility="private")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_same_run_id_returns_existing_row_200(disabled_client: AsyncClient) -> None:
    headers = {"Idempotency-Key": "run-1"}

    first = await disabled_client.post("/v1/scores", json=payload(), headers=headers)
    second = await disabled_client.post("/v1/scores", json=payload(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


async def test_private_board_refuses_unverified_write(disabled_client: AsyncClient) -> None:
    response = await disabled_client.post(
        "/v1/scores", json=payload(benchmark_id="priv", submitted_by=ANA)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "submissions to a private benchmark require a verified identity; this deployment runs "
        "with authentication disabled"
    )
