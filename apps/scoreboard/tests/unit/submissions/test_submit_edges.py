"""Edges of the clustered submit: the naming notice, legacy run ids, unreadable heads, lost races.

FEATURE: OME-1307 (E14).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from tortoise.exceptions import OperationalError

from scoreboard.scores.cluster_store import ClusterStore
from scoreboard.scores.models import IdempotencyKey, ReportedResult, Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore, _scoped_idempotency_key
from tests.unit.submissions._receipts import ANA, BRUNO, URL4_A, payload, post_score

pytestmark = pytest.mark.asyncio


async def test_a_known_system_under_another_name_gets_the_naming_notice_first(
    clustered_cf_client: AsyncClient,
) -> None:
    first = await post_score(clustered_cf_client, user=ANA, spec_id="kevins-best")

    second = await post_score(clustered_cf_client, user=BRUNO, spec_id="my-name", score=0.5)

    body = second.json()
    assert body["id"] == first.json()["id"]
    # INVARIANT: a known fingerprint always wins; the requested name is only told about the owner.
    assert body["spec_id"] == "kevins-best"
    assert body["notices"] == [
        {"code": "system_already_named", "name": "kevins-best", "owner": "ana"},
        {"code": "clustered_under", "score_id": first.json()["id"]},
    ]


async def test_a_legacy_run_id_replays_after_the_flag_flips(
    clustered_cf_client: AsyncClient,
) -> None:
    # SC-1 stays true after the flag flips: a row the legacy path made has no `run_id` on a result.
    legacy = await ScoreStore().submit(
        ScoreSubmission(**payload(submitted_by=ANA)),
        idempotency_key="old-run",
        identity_verified=True,
    )

    replay = await post_score(clustered_cf_client, user=ANA, key="old-run")

    assert replay.status_code == 200
    assert replay.json()["id"] == str(legacy.score.id)
    assert "reported_result" not in replay.json()
    assert replay.json()["reported_results_count"] == 0
    assert await Score.all().count() == 1


async def test_a_legacy_run_id_replays_with_the_original_result_when_there_is_one(
    clustered_cf_client: AsyncClient,
) -> None:
    legacy = await ScoreStore().submit(
        ScoreSubmission(**payload(submitted_by=ANA)),
        idempotency_key="old-run",
        identity_verified=True,
    )
    original = await ReportedResult.create(
        head_id=legacy.score.id, is_original=True, score=0.75, total_questions=4
    )

    replay = await post_score(clustered_cf_client, user=ANA, key="old-run")

    assert replay.status_code == 200
    assert replay.json()["reported_result"]["id"] == str(original.id)


async def test_a_legacy_mapping_this_code_did_not_write_is_not_honoured(
    clustered_cf_client: AsyncClient,
) -> None:
    # INVARIANT (OME-894): a reserved-namespace mapping counts only when it carries the scheme this
    # code stamps. An old replica can bind a predictable `sfp-` token to a row an attacker chose.
    legacy = await ScoreStore().submit(
        ScoreSubmission(**payload(benchmark_id="priv", submitted_by=ANA)),
        idempotency_key="old-run",
        identity_verified=True,
    )
    stored = _scoped_idempotency_key("old-run", ANA, per_submitter=True)
    assert stored is not None
    await IdempotencyKey.filter(key=stored).update(scheme=None)

    response = await post_score(clustered_cf_client, user=ANA, benchmark_id="priv", key="old-run")

    assert response.status_code == 201
    assert response.json()["reported_result"]["is_original"] is False
    assert response.json()["id"] == str(legacy.score.id)


async def test_a_private_head_with_an_unreadable_url4_is_skipped_not_fatal(
    clustered_cf_client: AsyncClient,
) -> None:
    # A head stored before E14 can hold text that the fingerprinter refuses. It never matches.
    old = await ScoreStore().submit(
        ScoreSubmission(
            **payload(benchmark_id="priv", submitted_by=ANA, url4_expression="url4://bench/a")
        ),
        identity_verified=True,
    )

    response = await post_score(clustered_cf_client, user=ANA, benchmark_id="priv")

    assert response.status_code == 201
    assert response.json()["id"] != str(old.score.id)
    assert response.json()["reported_result"]["is_original"] is True
    assert response.json()["url4_expression"] == URL4_A


async def test_a_version_bound_after_the_pre_check_is_a_409_not_a_503(
    clustered_cf_client: AsyncClient,
    sign_receipt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A concurrent winner binds the version between this request's pre-check and its insert. The
    # unique `cache_version_id` then rejects the insert twice, and the answer is the typed 409.
    receipt = sign_receipt(vid=str(uuid.uuid4()))
    await post_score(clustered_cf_client, key="run-a", receipt=receipt)

    async def blind(self: ClusterStore, *args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(ClusterStore, "_check_bindings", blind)

    response = await post_score(clustered_cf_client, key="run-b", receipt=receipt, score=0.5)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cache_version_already_bound"
    assert await ReportedResult.all().count() == 1


async def test_a_store_that_is_down_answers_503_on_the_results_list(
    clustered_cf_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted = await post_score(clustered_cf_client)

    async def down(self: ClusterStore, *args: Any, **kwargs: Any) -> None:
        raise OperationalError("down")

    monkeypatch.setattr(ClusterStore, "results_page", down)

    response = await clustered_cf_client.get(f"/v1/scores/{posted.json()['id']}/results")

    assert response.status_code == 503
    assert response.json() == {"detail": "score store unavailable"}


async def test_a_store_that_is_down_answers_503_before_the_head_is_read(
    clustered_cf_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(*args: Any, **kwargs: Any) -> None:
        raise OperationalError("down")

    monkeypatch.setattr(Score, "get_or_none", down)

    response = await clustered_cf_client.get(f"/v1/scores/{uuid.uuid4()}/results")

    assert response.status_code == 503
