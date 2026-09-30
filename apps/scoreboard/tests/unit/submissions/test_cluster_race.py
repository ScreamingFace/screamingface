"""SC-10a — the head insert loses a race once, then joins the winner (SC-D2, SR-D2).

FEATURE: OME-1307 (E14). INVARIANT: `IntegrityError` subclasses `OperationalError`, which the route
maps to 503. It must never leave `submit`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient

from scoreboard.scores.cluster_store import ClusterStore
from scoreboard.scores.models import ReportedResult, Score
from tests.unit.submissions._receipts import post_score

pytestmark = pytest.mark.asyncio


def _lose_the_first_lookup(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    real = ClusterStore._find_public_head
    calls: list[int] = []

    async def racing(self: ClusterStore, **kwargs: Any) -> Score | None:
        calls.append(1)
        if len(calls) == 1:
            return None
        return await real(self, **kwargs)

    monkeypatch.setattr(ClusterStore, "_find_public_head", racing)
    return calls


async def test_head_insert_integrity_error_retries_once_as_reported_result(
    clustered_cf_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await post_score(clustered_cf_client, key="run-a")
    head_id = first.json()["id"]
    calls = _lose_the_first_lookup(monkeypatch)

    # Same url4, spec and score: the new head hash collides with the head on the unique
    # `content_hash`, exactly what a concurrent first submit does.
    second = await post_score(clustered_cf_client, key="run-b")

    assert second.status_code == 201
    assert second.json()["id"] == head_id
    assert second.json()["reported_result"]["is_original"] is False
    assert len(calls) == 2
    assert await Score.all().count() == 1
    assert await ReportedResult.all().count() == 2


async def test_a_second_lost_race_is_a_409_never_a_503(
    clustered_cf_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Known limit: a head whose content hash equals a head that is already linked to another
    # revision loses twice. The route answers 409 ConcurrentScoreUpdate, not 503.
    await post_score(clustered_cf_client, key="run-a")

    async def never_finds(self: ClusterStore, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(ClusterStore, "_find_public_head", never_finds)

    response = await post_score(clustered_cf_client, key="run-b")

    assert response.status_code == 409
    assert await Score.all().count() == 1
    assert await ReportedResult.all().count() == 1


async def test_a_concurrent_resend_of_one_run_makes_one_result(
    clustered_cf_client: AsyncClient,
) -> None:
    responses = await asyncio.gather(
        post_score(clustered_cf_client, key="run-a"), post_score(clustered_cf_client, key="run-a")
    )

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert (
        responses[0].json()["reported_result"]["id"] == responses[1].json()["reported_result"]["id"]
    )
    assert await ReportedResult.all().count() == 1
    assert await Score.all().count() == 1
