"""SC-8a — the `disabled` dev/local fallback of the submit flow (D5).

FEATURE: OME-1307 (E14). INVARIANT: an unverified name never owns a system (`System.owner` is NOT
NULL and names are global), so the fallback keeps today's content-hash clustering, calls no
registry, and skips the receipt `sub` check (C3). It still records the cache version. This is the
only `disabled` test of the submit flow.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient

from scoreboard.scores.models import ReportedResult, Score, System
from tests.unit.submissions._receipts import payload

pytestmark = pytest.mark.asyncio


def _body(with_submitter: bool, **overrides: Any) -> dict[str, Any]:
    body = payload(**overrides)
    if with_submitter:
        body["submitted_by"] = "kevin"
    else:
        del body["submitted_by"]
    return body


@pytest.mark.parametrize("with_submitter", [False, True], ids=["no-submitter", "free-text"])
async def test_disabled_fallback_clusters_by_content_hash_no_registry_no_sub_check(
    clustered_client: AsyncClient, sign_receipt: Callable[..., str], with_submitter: bool
) -> None:
    first = await clustered_client.post(
        "/v1/scores", json=_body(with_submitter), headers={"Idempotency-Key": "run-1"}
    )
    second = await clustered_client.post(
        "/v1/scores", json=_body(with_submitter), headers={"Idempotency-Key": "run-2"}
    )

    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["reported_results_count"] == 2
    assert first.json()["reported_result"]["is_original"] is True
    assert second.json()["reported_result"]["is_original"] is False
    assert await System.all().count() == 0
    head = await Score.get(id=first.json()["id"])
    assert head.system_revision_id is None
    assert head.spec_id == "kevins-best"


async def test_disabled_fallback_accepts_a_receipt_of_another_subject(
    clustered_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    vid = uuid.uuid4()

    response = await clustered_client.post(
        "/v1/scores",
        json={
            **_body(True),
            "cache_version_receipt": sign_receipt(sub="someone-else", vid=str(vid)),
        },
    )

    assert response.status_code == 201, response.text
    stored = await ReportedResult.get(id=response.json()["reported_result"]["id"])
    assert stored.cache_version_id == vid
    assert stored.cache_version_sha256 == "a" * 64
    assert (stored.cache_entry_count, stored.cache_call_count) == (412, 420)
    assert stored.cache_coverage_status == "complete"


async def test_disabled_fallback_ignores_revision_of(clustered_client: AsyncClient) -> None:
    response = await clustered_client.post(
        "/v1/scores", json={**_body(True), "revision_of": "does-not-exist"}
    )

    assert response.status_code == 201
    assert await System.all().count() == 0
