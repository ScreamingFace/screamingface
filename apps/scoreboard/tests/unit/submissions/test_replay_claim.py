"""SC-14 — a replay run stores its provenance and is labelled; a bad claim is refused (rule R).

FEATURE: OME-1307 (E14). C4 trust rule: the counts are stored as reported and labelled "reported by
client"; the claim itself must name a result the caller may replay.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient

from scoreboard.scores.models import Benchmark, ReportedResult
from tests.unit.submissions._receipts import ANA, BRUNO, post_score

pytestmark = pytest.mark.asyncio


def _claim(result_id: str, version_id: str, **overrides: Any) -> dict[str, Any]:
    claim: dict[str, Any] = {
        "result_id": result_id,
        "cache_version_id": version_id,
        "hits": 10,
        "misses": 2,
        "repeated_key_collapses": 3,
    }
    claim.update(overrides)
    return claim


async def _original(
    client: AsyncClient, sign_receipt: Callable[..., str], **overrides: Any
) -> tuple[str, str]:
    """Ana's frozen run: the result id and its cache version id."""
    vid = str(uuid.uuid4())
    response = await post_score(client, user=ANA, receipt=sign_receipt(vid=vid), **overrides)
    assert response.status_code == 201, response.text
    return response.json()["reported_result"]["id"], vid


async def test_replay_run_stores_provenance_and_label(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    result_id, vid = await _original(clustered_cf_client, sign_receipt)
    baseline_id, _ = await _original(clustered_cf_client, sign_receipt, score=0.4)

    response = await post_score(
        clustered_cf_client,
        user=BRUNO,
        score=0.7,
        replay=_claim(result_id, vid, pinned_baseline_result_id=baseline_id),
    )

    assert response.status_code == 201, response.text
    stored = await ReportedResult.get(id=response.json()["reported_result"]["id"])
    assert getattr(stored, "replayed_from_result_id") == uuid.UUID(result_id)
    assert (stored.replay_hits, stored.replay_misses) == (10, 2)
    assert stored.replay_repeated_key_collapses == 3
    assert getattr(stored, "pinned_baseline_result_id") == uuid.UUID(baseline_id)
    head_id = response.json()["id"]
    listing = (await clustered_cf_client.get(f"/v1/scores/{head_id}/results")).json()["results"]
    replayed = next(item for item in listing if item["id"] == str(stored.id))
    assert replayed["replay"]["reported_by"] == "client"
    assert replayed["replay"]["hits"] == 10
    assert replayed["labels"][0].startswith("replay of ")


async def test_the_submit_response_labels_the_replay_as_reported_by_the_client(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    result_id, vid = await _original(clustered_cf_client, sign_receipt)

    response = await post_score(
        clustered_cf_client, user=BRUNO, score=0.7, replay=_claim(result_id, vid)
    )

    replay = response.json()["reported_result"]["replay"]
    assert replay["reported_by"] == "client"
    assert replay["replayed_from_result_id"] == result_id
    assert replay["pinned_baseline_result_id"] is None


async def test_the_owner_may_replay_a_private_board_result(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    result_id, vid = await _original(clustered_cf_client, sign_receipt, benchmark_id="priv")

    response = await post_score(
        clustered_cf_client,
        user=ANA,
        benchmark_id="priv",
        score=0.7,
        replay=_claim(result_id, vid),
    )

    assert response.status_code == 201, response.text


async def _invalid_claims(
    client: AsyncClient, sign_receipt: Callable[..., str]
) -> dict[str, dict[str, Any]]:
    result_id, vid = await _original(client, sign_receipt)
    private_id, private_vid = await _original(client, sign_receipt, benchmark_id="priv")
    gated_id, gated_vid = await _original(client, sign_receipt, benchmark_id="gated")
    # INVARIANT: a claim may only name a result of the board it is posted on (C4 trust rule;
    # C6/RP-E4 refuses the same grant with 422). `other` is public and redistributable, so only the
    # benchmark check can refuse this claim.
    await Benchmark.create(id="other", display_name="Other", redistributable=True)
    other_id, other_vid = await _original(client, sign_receipt, benchmark_id="other")
    return {
        "unknown-result": _claim(str(uuid.uuid4()), vid),
        "wrong-version": _claim(result_id, str(uuid.uuid4())),
        "private-result-of-another-user": _claim(private_id, private_vid),
        "not-redistributable-result-of-another-user": _claim(gated_id, gated_vid),
        "result-of-another-benchmark": _claim(other_id, other_vid),
        "unknown-baseline": _claim(result_id, vid, pinned_baseline_result_id=str(uuid.uuid4())),
    }


@pytest.mark.parametrize(
    "case",
    [
        "unknown-result",
        "wrong-version",
        "private-result-of-another-user",
        "not-redistributable-result-of-another-user",
        "result-of-another-benchmark",
        "unknown-baseline",
    ],
)
async def test_an_invalid_replay_claim_is_422_and_nothing_is_written(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str], case: str
) -> None:
    claims = await _invalid_claims(clustered_cf_client, sign_receipt)
    before = await ReportedResult.all().count()

    response = await post_score(clustered_cf_client, user=BRUNO, score=0.7, replay=claims[case])

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_replay_claim"
    assert await ReportedResult.all().count() == before


async def test_a_withdrawn_result_cannot_be_replayed_by_another_user(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    from scoreboard.scores.models import CacheVersionPublication

    result_id, vid = await _original(clustered_cf_client, sign_receipt)
    await CacheVersionPublication.filter(result_id=result_id).update(state="withdrawn")

    refused = await post_score(
        clustered_cf_client, user=BRUNO, score=0.7, replay=_claim(result_id, vid)
    )
    owner = await post_score(
        clustered_cf_client, user=ANA, score=0.7, replay=_claim(result_id, vid)
    )

    assert refused.status_code == 422
    assert owner.status_code == 201


# X-SEC-1 — the baseline is checked like the replayed result: same board, and a result this caller
# could replay. INVARIANT: a stranger's row must not name a result it may not see, because the
# `pinned_baseline_result_id` FK is NO ACTION (D8) and would block the owner's delete or purge.


async def _private_result(client: AsyncClient) -> str:
    response = await post_score(client, user=ANA, benchmark_id="priv", key="ana-private")
    assert response.status_code == 201, response.text
    return response.json()["reported_result"]["id"]


async def _other_board_result(client: AsyncClient) -> str:
    response = await post_score(client, user=ANA, benchmark_id="gated", key="ana-gated")
    assert response.status_code == 201, response.text
    return response.json()["reported_result"]["id"]


@pytest.mark.parametrize("board", ["private", "gated"])
async def test_a_baseline_the_caller_may_not_replay_is_invalid_and_stores_nothing(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str], board: str
) -> None:
    result_id, vid = await _original(clustered_cf_client, sign_receipt)
    baseline_id = (
        await _private_result(clustered_cf_client)
        if board == "private"
        else await _other_board_result(clustered_cf_client)
    )
    before = await ReportedResult.all().count()

    response = await post_score(
        clustered_cf_client,
        user=BRUNO,
        score=0.7,
        replay=_claim(result_id, vid, pinned_baseline_result_id=baseline_id),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_replay_claim"
    assert await ReportedResult.all().count() == before


async def test_a_baseline_the_caller_owns_on_a_private_board_is_still_refused_on_a_public_board(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    # WHY: even the owner of a private result cannot pin it as the baseline of a run on ANOTHER
    # board; the board rule comes first (a grant never crosses boards, C6/RP-E4).
    result_id, vid = await _original(clustered_cf_client, sign_receipt)
    own_private = await _private_result(clustered_cf_client)

    response = await post_score(
        clustered_cf_client,
        user=ANA,
        score=0.7,
        replay=_claim(result_id, vid, pinned_baseline_result_id=own_private),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_replay_claim"
