"""Edge rows of the replay grant route: errors, read-only, no logged secret (RP-9, RP-10).

FEATURE: OME-1307 (E14) replay grants. INVARIANT: the route writes nothing and logs no grant, key or
caller email.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from tortoise.exceptions import OperationalError

from scoreboard.scores.models import CacheVersionPublication, ReportedResult, Score
from tests.unit.replay._helpers import request_grant
from tests.unit.replay.conftest import GrantKey, SeedResult, SpySigner
from tests.unit.submissions._receipts import ANA, BRUNO

pytestmark = pytest.mark.asyncio


async def test_a_store_that_is_down_answers_503_with_the_private_headers(
    grant_cf_app: FastAPI, grant_cf_client: AsyncClient, spy: SpySigner
) -> None:
    class _Down:
        async def resolve(self, *args: Any, **kwargs: Any) -> Any:
            raise OperationalError("database is down")

    grant_cf_app.state.replay_resolver = _Down()

    response = await request_grant(grant_cf_client, f"result:{uuid.uuid4()}", user=BRUNO)

    assert response.status_code == 503
    assert response.json() == {"detail": "score store unavailable"}
    assert response.headers["cache-control"] == "private, no-store"
    assert spy.calls == []


async def test_a_score_pin_of_an_unknown_head_is_the_same_404(
    grant_cf_client: AsyncClient, spy: SpySigner
) -> None:
    unknown = await request_grant(grant_cf_client, f"score:{uuid.uuid4()}", user=BRUNO)
    other = await request_grant(grant_cf_client, f"result:{uuid.uuid4()}", user=BRUNO)

    assert unknown.status_code == 404
    assert unknown.content == other.content
    assert spy.calls == []


async def test_a_result_with_no_cache_version_never_resolves_by_id(
    grant_cf_client: AsyncClient, seed_result: SeedResult, spy: SpySigner
) -> None:
    unversioned = await seed_result(reporter=ANA, receipt=False)

    by_result = await request_grant(grant_cf_client, f"result:{unversioned.result_id}", user=ANA)
    by_score = await request_grant(grant_cf_client, f"score:{unversioned.head_id}", user=ANA)

    assert by_result.status_code == by_score.status_code == 404
    assert spy.calls == []


async def test_a_withdrawn_public_result_on_another_board_gives_410_before_422(
    grant_cf_client: AsyncClient, seed_result: SeedResult
) -> None:
    # The fixed order is 404 class, then 410, then 422 (plan 4.4 rule 2).
    seeded = await seed_result(benchmark="other", reporter=ANA)
    await CacheVersionPublication.filter(result_id=seeded.result_id).update(state="withdrawn")

    response = await request_grant(
        grant_cf_client, f"result:{seeded.result_id}", user=BRUNO, benchmark_id="pub"
    )

    assert response.status_code == 410


async def test_the_route_writes_nothing_and_logs_no_grant_key_or_email(
    grant_cf_client: AsyncClient,
    grant_key: GrantKey,
    seed_result: SeedResult,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seeded = await seed_result(reporter=ANA)
    heads, results = await Score.all().count(), await ReportedResult.all().count()
    publications = await CacheVersionPublication.all().count()

    with caplog.at_level(logging.DEBUG):
        response = await request_grant(grant_cf_client, f"result:{seeded.result_id}", user=BRUNO)

    assert response.status_code == 200
    assert await Score.all().count() == heads
    assert await ReportedResult.all().count() == results
    assert await CacheVersionPublication.all().count() == publications
    logged = caplog.text
    assert response.json()["grant"] not in logged
    assert grant_key.private_b64 not in logged
    assert BRUNO not in logged
    assert seeded.result_id in logged


async def test_an_unknown_body_field_is_refused(grant_cf_client: AsyncClient) -> None:
    response = await grant_cf_client.post(
        "/v1/replay-grants",
        json={"pin": "kevins-best", "benchmark_id": "pub", "ttl": 99999},
        headers={"X-User-Email": BRUNO},
    )

    assert response.status_code == 422
