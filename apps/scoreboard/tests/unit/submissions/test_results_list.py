"""SC-17, SC-17b — `GET /v1/scores/{score_id}/results` (C10).

FEATURE: OME-1307 (E14). INVARIANT: the privacy rules are `get_score`'s: a private head is 404 to
everyone but its owner, the refusal carries the private cache policy, and the answer is re-checked
against fresh visibility before a public body leaves (OME-894, SC-D9).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from scoreboard.scores.cluster_store import ClusterStore
from scoreboard.scores.models import Benchmark, ReportedResult, Score
from tests.unit.submissions._receipts import ANA, BRUNO, as_user, post_score

pytestmark = pytest.mark.asyncio

_T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


async def _head(client: AsyncClient, **overrides: Any) -> str:
    response = await post_score(client, **overrides)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _seed_results(head_id: str) -> list[str]:
    """Five extra results with set times. Two share a time, to prove the `id DESC` tie-break."""
    # (offset in minutes, id number): newest first the order must be 5, 4, 3, 2, 1 by (time, id).
    plan = [(1, 1), (2, 2), (3, 3), (3, 4), (5, 5)]
    ids: list[str] = []
    for minutes, number in plan:
        row = await ReportedResult.create(
            id=uuid.UUID(int=number),
            head_id=head_id,
            is_original=False,
            score=0.1 * number,
            total_questions=4,
        )
        await ReportedResult.filter(id=row.id).update(submitted_at=_T0 + timedelta(minutes=minutes))
        ids.append(str(row.id))
    return ids


async def test_results_list_cursor_paged_newest_first(clustered_cf_client: AsyncClient) -> None:
    head_id = await _head(clustered_cf_client)
    await ReportedResult.filter(head_id=head_id).update(submitted_at=_T0 - timedelta(days=1))
    ids = await _seed_results(head_id)
    original = (await ReportedResult.get(head_id=head_id, is_original=True)).id
    url = f"/v1/scores/{head_id}/results"

    page_1 = (await clustered_cf_client.get(url, params={"limit": 2})).json()
    page_2 = (
        await clustered_cf_client.get(url, params={"limit": 2, "cursor": page_1["next_cursor"]})
    ).json()
    page_3 = (
        await clustered_cf_client.get(url, params={"limit": 2, "cursor": page_2["next_cursor"]})
    ).json()

    order = [item["id"] for page in (page_1, page_2, page_3) for item in page["results"]]
    assert order == [ids[4], ids[3], ids[2], ids[1], ids[0], str(original)]
    assert [len(p["results"]) for p in (page_1, page_2, page_3)] == [2, 2, 2]
    assert page_1["next_cursor"] and page_2["next_cursor"]
    assert page_3["next_cursor"] is None


async def test_results_list_defaults_to_fifty_and_carries_the_result_shape(
    clustered_cf_client: AsyncClient,
) -> None:
    head_id = await _head(clustered_cf_client)

    body = (await clustered_cf_client.get(f"/v1/scores/{head_id}/results")).json()

    assert body["next_cursor"] is None
    (item,) = body["results"]
    assert item["is_original"] is True
    assert item["score_id"] == head_id
    assert item["reporter"] == "ana"
    assert item["cache_version"] is None
    assert item["labels"] == []


async def test_results_list_rejects_a_bad_cursor_and_a_bad_limit(
    clustered_cf_client: AsyncClient,
) -> None:
    head_id = await _head(clustered_cf_client)
    url = f"/v1/scores/{head_id}/results"

    bad_cursor = await clustered_cf_client.get(url, params={"cursor": "!!!"})
    too_many = await clustered_cf_client.get(url, params={"limit": 201})
    zero = await clustered_cf_client.get(url, params={"limit": 0})

    assert bad_cursor.status_code == 422
    assert bad_cursor.json()["detail"]["code"] == "invalid_cursor"
    assert too_many.status_code == 422
    assert zero.status_code == 422


async def test_an_unknown_score_is_the_same_404_as_get_score(
    clustered_cf_client: AsyncClient,
) -> None:
    response = await clustered_cf_client.get(f"/v1/scores/{uuid.uuid4()}/results")

    assert response.status_code == 404
    assert response.json() == {"detail": "score not found"}


async def test_a_private_head_is_404_to_everyone_but_its_owner(
    clustered_cf_client: AsyncClient,
) -> None:
    head_id = await _head(clustered_cf_client, benchmark_id="priv", user=ANA)
    url = f"/v1/scores/{head_id}/results"

    bruno = await clustered_cf_client.get(url, headers=as_user(BRUNO))
    nobody = await clustered_cf_client.get(url)
    ana = await clustered_cf_client.get(url, headers=as_user(ANA))
    missing = await clustered_cf_client.get(f"/v1/scores/{uuid.uuid4()}/results")

    assert bruno.status_code == nobody.status_code == 404
    assert bruno.json() == nobody.json() == missing.json() == {"detail": "score not found"}
    assert ana.status_code == 200
    assert len(ana.json()["results"]) == 1
    for response in (bruno, nobody, ana, missing):
        assert response.headers["Cache-Control"] == "private, no-store"


async def test_a_private_head_is_not_told_apart_by_a_bad_cursor(
    clustered_cf_client: AsyncClient,
) -> None:
    head_id = await _head(clustered_cf_client, benchmark_id="priv", user=ANA)

    response = await clustered_cf_client.get(
        f"/v1/scores/{head_id}/results", params={"cursor": "!!!"}, headers=as_user(BRUNO)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "score not found"}


async def test_results_list_of_a_board_that_turns_private_mid_read_gives_no_public_data(
    clustered_cf_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT (OME-894, SC-D9): the page was read while the board was public; the board turns
    # private before the answer leaves, and the answer must then be the private 404.
    head_id = await _head(clustered_cf_client, user=ANA)
    real = ClusterStore.results_page

    async def flip_after_read(self: ClusterStore, *args: Any, **kwargs: Any) -> Any:
        rows = await real(self, *args, **kwargs)
        await Benchmark.filter(id="pub").update(visibility="private")
        return rows

    monkeypatch.setattr(ClusterStore, "results_page", flip_after_read)

    response = await clustered_cf_client.get(
        f"/v1/scores/{head_id}/results", headers=as_user(BRUNO)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "score not found"}
    assert "results" not in response.text


async def test_disabled_fallback_results_list_public_ok_private_404(
    clustered_client: AsyncClient,
) -> None:
    # The only `disabled` test of this flow. A private write needs a verified identity, so the
    # private head is seeded with the model. `ReadIdentity` ignores a forged header in this mode.
    public = await Score.create(
        benchmark_id="pub",
        spec_id="s",
        url4_expression="x",
        submitted_by="kevin",
        score=0.5,
        total_questions=1,
        ran_with_providers=["openai"],
        content_hash="h-pub",
    )
    private = await Score.create(
        benchmark_id="priv",
        spec_id="s",
        url4_expression="x",
        submitted_by=ANA,
        score=0.5,
        total_questions=1,
        ran_with_providers=["openai"],
        content_hash="h-priv",
    )
    for head in (public, private):
        await ReportedResult.create(head_id=head.id, is_original=True, score=0.5, total_questions=1)

    open_list = await clustered_client.get(f"/v1/scores/{public.id}/results")
    anonymous = await clustered_client.get(f"/v1/scores/{private.id}/results")
    forged = await clustered_client.get(f"/v1/scores/{private.id}/results", headers=as_user(ANA))

    assert open_list.status_code == 200
    assert len(open_list.json()["results"]) == 1
    assert anonymous.status_code == forged.status_code == 404
