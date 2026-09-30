"""SC-4, SC-5, SC-6 — the receipt is verified BEFORE any write (C3, C4).

FEATURE: OME-1307 (E14). D5: the main path runs `cloudflare_headers`, so the receipt `sub` is
compared with the verified email. The `disabled` case is SC-8a in test_clustering.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from httpx import AsyncClient

from scoreboard.scores.models import CacheVersionPublication, ReportedResult, Score, System
from tests.unit.submissions._receipts import (
    ANA,
    BRUNO,
    KID,
    ReceiptKey,
    make_receipt,
    new_receipt_key,
    post_score,
)

pytestmark = pytest.mark.asyncio


async def _nothing_written() -> None:
    assert await Score.all().count() == 0
    assert await ReportedResult.all().count() == 0
    assert await System.all().count() == 0
    assert await CacheVersionPublication.all().count() == 0


def _wrong_signer(key: ReceiptKey) -> str:
    return make_receipt(new_receipt_key(), kid=KID)


def _hs256(key: ReceiptKey) -> str:
    return jwt.encode({"iss": "aigateway"}, "s" * 32, algorithm="HS256", headers={"kid": KID})


@pytest.mark.parametrize(
    ("build", "reason"),
    [
        pytest.param(_wrong_signer, "bad_signature", id="signed-by-another-key"),
        pytest.param(lambda key: make_receipt(key, kid="nope"), "unknown_kid", id="unknown-kid"),
        pytest.param(_hs256, "bad_alg", id="hs256"),
        pytest.param(lambda key: "not-a-jws", "malformed", id="not-a-jws"),
        pytest.param(lambda key: make_receipt(key, aud="x"), "bad_audience", id="audience"),
    ],
)
async def test_receipt_bad_signature_422_nothing_written(
    clustered_cf_client: AsyncClient, receipt_key: ReceiptKey, build: Any, reason: str
) -> None:
    response = await post_score(clustered_cf_client, receipt=build(receipt_key))

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_cache_version_receipt"
    assert detail["reason"] == reason
    await _nothing_written()


async def test_a_refused_receipt_counts_by_reason(
    clustered_cf_client: AsyncClient, clustered_cf_app: Any
) -> None:
    await post_score(clustered_cf_client, receipt="not-a-jws")

    metrics = clustered_cf_app.state.metrics
    sample = metrics.registry.get_sample_value(
        "scoreboard_receipt_rejections_total", {"reason": "malformed"}
    )
    assert sample == 1.0


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"sub": "other@x.org"}, id="sub-is-someone-else"),
        pytest.param({"tid": "b" * 32}, id="tid-is-another-trace"),
    ],
)
async def test_receipt_sub_or_tid_mismatch_403(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str], overrides: dict[str, Any]
) -> None:
    response = await post_score(clustered_cf_client, receipt=sign_receipt(**overrides))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "cache_version_not_yours"
    await _nothing_written()


async def test_a_receipt_needs_the_trace_id_of_the_report(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    response = await post_score(clustered_cf_client, receipt=sign_receipt(), trace_id=None)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "cache_version_not_yours"


async def test_receipt_sub_is_compared_with_casefold_and_strip(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    response = await post_score(clustered_cf_client, receipt=sign_receipt(sub="ANA@X.org "))

    assert response.status_code == 201
    assert response.json()["reported_result"]["cache_version"] is not None


async def test_receipt_vid_bound_to_other_run_409(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    vid = str(uuid.uuid4())
    receipt = sign_receipt(vid=vid)
    run_a = await post_score(clustered_cf_client, key="run-a", receipt=receipt)

    run_b = await post_score(clustered_cf_client, key="run-b", receipt=receipt, score=0.5)
    run_a_again = await post_score(clustered_cf_client, key="run-a", receipt=receipt)

    assert run_a.status_code == 201
    assert run_b.status_code == 409
    assert run_b.json()["detail"]["code"] == "cache_version_already_bound"
    assert run_a_again.status_code == 200
    assert await ReportedResult.all().count() == 1


async def test_a_second_participant_cannot_claim_the_version_of_the_first(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    vid = str(uuid.uuid4())
    await post_score(clustered_cf_client, key="run-a", receipt=sign_receipt(vid=vid), user=ANA)

    stolen = await post_score(
        clustered_cf_client, key="run-b", receipt=sign_receipt(vid=vid, sub=BRUNO), user=BRUNO
    )

    assert stolen.status_code == 409
    assert stolen.json()["detail"]["code"] == "cache_version_already_bound"
