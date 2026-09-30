"""SC-22a, SC-22b — the leaderboard row carries a result count only from two results.

FEATURE: OME-1307 (E14). INVARIANT: a legacy payload stays byte-identical: with one result the two
new keys are absent, and `GET /v1/scores/{id}` never gains the submit-only keys.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore
from tests.unit.submissions._receipts import ANA, BRUNO, payload, post_score

pytestmark = pytest.mark.asyncio


async def test_leaderboard_row_carries_count_only_from_two_results(
    clustered_cf_client: AsyncClient,
) -> None:
    first = await post_score(clustered_cf_client, user=ANA)
    head_id = first.json()["id"]

    one = (await clustered_cf_client.get("/v1/leaderboard/pub")).json()["entries"][0]
    await post_score(clustered_cf_client, user=BRUNO, score=0.5)
    two = (await clustered_cf_client.get("/v1/leaderboard/pub")).json()["entries"][0]

    assert "score_id" not in one
    assert "reported_results_count" not in one
    assert two["reported_results_count"] == 2
    assert two["score_id"] == head_id


async def test_score_json_unchanged_when_no_e14_fields(clustered_cf_client: AsyncClient) -> None:
    legacy = await ScoreStore().submit(
        ScoreSubmission(**payload(benchmark_id="gated", submitted_by=ANA)), identity_verified=True
    )

    body = (await clustered_cf_client.get(f"/v1/scores/{legacy.score.id}")).json()

    for key in ("reported_result", "reported_results_count", "notices"):
        assert key not in body


async def test_the_submit_answer_carries_the_e14_keys_and_the_get_does_not(
    clustered_cf_client: AsyncClient,
) -> None:
    posted = (await post_score(clustered_cf_client)).json()

    fetched = (await clustered_cf_client.get(f"/v1/scores/{posted['id']}")).json()

    assert {"reported_result", "reported_results_count", "notices"} <= set(posted)
    assert not {"reported_result", "reported_results_count", "notices"} & set(fetched)
