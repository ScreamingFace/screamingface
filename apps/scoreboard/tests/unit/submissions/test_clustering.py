"""SC-7, SC-8, SC-9, SC-11, SC-12, SC-13, SC-16 and the metrics — the clustered submit (C4).

FEATURE: OME-1307 (E14). D5: the main path runs `cloudflare_headers`, so the system owner and the
reporter are the verified email of the caller. STORY: as Ana I submit my system and it gets a
name; as Bruno I submit the same system and my run joins Ana's head instead of making a second row.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient

from scoreboard.adapters.url4_fingerprinter import Url4Fingerprinter
from scoreboard.scores.models import CacheVersionPublication, ReportedResult, Score, System
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore
from tests.unit.submissions._receipts import ANA, BRUNO, URL4_A, URL4_B, payload, post_score

pytestmark = pytest.mark.asyncio


async def test_first_submit_creates_head_and_original_result_with_version(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    vid = str(uuid.uuid4())

    response = await post_score(clustered_cf_client, receipt=sign_receipt(vid=vid))

    assert response.status_code == 201
    body = response.json()
    result = body["reported_result"]
    assert result["is_original"] is True
    assert result["score_id"] == body["id"]
    assert result["cache_version"] == {
        "id": vid,
        "sha256": "a" * 64,
        "entry_count": 412,
        "call_count": 420,
        "coverage_status": "complete",
    }
    assert result["publication_state"] == "private"
    assert body["reported_results_count"] == 1
    assert body["spec_id"] == "kevins-best"
    assert body["system_revision_id"] is not None
    assert body["notices"] == []
    head = await Score.get(id=body["id"])
    assert head.system_revision_id is not None
    system = await System.get(name="kevins-best")
    assert system.owner == ANA


async def test_same_system_second_reporter_appends_result_no_new_head(
    clustered_cf_client: AsyncClient, sign_receipt: Callable[..., str]
) -> None:
    first = await post_score(clustered_cf_client, user=ANA, receipt=sign_receipt(sub=ANA))

    second = await post_score(
        clustered_cf_client, user=BRUNO, receipt=sign_receipt(sub=BRUNO), score=0.5
    )

    assert second.status_code == 201
    body = second.json()
    assert body["id"] == first.json()["id"]
    assert body["reported_result"]["is_original"] is False
    assert body["reported_result"]["reporter"] == "bruno"
    assert body["reported_results_count"] == 2
    assert body["notices"] == [{"code": "clustered_under", "score_id": first.json()["id"]}]
    assert await Score.all().count() == 1
    assert (await System.get(name="kevins-best")).owner == ANA
    assert await CacheVersionPublication.all().count() == 2


async def test_later_result_never_changes_head_ranked_columns(
    clustered_cf_client: AsyncClient,
) -> None:
    first = await post_score(clustered_cf_client, user=ANA)
    head_id = first.json()["id"]

    second = await post_score(
        clustered_cf_client,
        user=BRUNO,
        score=0.5,
        total_questions=8,
        correct_questions=4,
        run_cost_usd="9.000000",
    )

    assert second.json()["reported_result"]["score"] == 0.5
    assert second.json()["reported_result"]["total_questions"] == 8
    head = (await clustered_cf_client.get(f"/v1/scores/{head_id}")).json()
    board = (await clustered_cf_client.get("/v1/leaderboard/pub")).json()["entries"]
    assert (head["score"], head["total_questions"], head["correct_questions"]) == (0.75, 4, 3)
    assert head["run_cost_usd"] == "1.250000"
    assert len(board) == 1
    assert (board[0]["score"], board[0]["total_questions"]) == (0.75, 4)
    assert board[0]["run_cost_usd"] == "1.250000"
    assert board[0]["submitted_by"] == "ana"


async def test_the_same_submitter_resubmitting_the_system_is_another_reported_result(
    clustered_cf_client: AsyncClient,
) -> None:
    first = await post_score(clustered_cf_client, user=ANA)
    again = await post_score(clustered_cf_client, user=ANA, score=0.6)

    assert again.json()["id"] == first.json()["id"]
    assert again.json()["reported_results_count"] == 2


async def test_a_later_reporter_authors_and_paper_url_belong_to_the_head_and_are_ignored(
    clustered_cf_client: AsyncClient,
) -> None:
    first = await post_score(clustered_cf_client, user=ANA, paper_url="https://paper.test/a")

    second = await post_score(
        clustered_cf_client,
        user=BRUNO,
        score=0.5,
        paper_url="https://paper.test/b",
        authors=["bruno@y.org"],
    )

    assert second.json()["paper_url"] == "https://paper.test/a"
    assert (await Score.get(id=first.json()["id"])).authors is None


async def test_legacy_head_same_url4_links_and_clusters(
    clustered_cf_client: AsyncClient,
) -> None:
    legacy = await ScoreStore().submit(
        ScoreSubmission(**payload(submitted_by=ANA)), identity_verified=True
    )

    response = await post_score(clustered_cf_client, user=ANA)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(legacy.score.id)
    assert body["reported_result"]["is_original"] is False
    assert body["system_revision_id"] is not None
    assert await Score.all().count() == 1
    assert (await Score.get(id=legacy.score.id)).system_revision_id is not None


async def test_cluster_key_uses_the_resolved_revision_not_client_metadata(
    clustered_cf_client: AsyncClient,
) -> None:
    first = await post_score(
        clustered_cf_client, benchmark_revision="r2", metadata={"benchmark_revision": "r1"}
    )
    second = await post_score(
        clustered_cf_client,
        benchmark_revision="r2",
        metadata={"benchmark_revision": "r3"},
        score=0.5,
    )

    assert second.json()["id"] == first.json()["id"]
    assert await Score.all().count() == 1
    assert (await Score.get(id=first.json()["id"])).benchmark_revision == "r2"


async def test_another_benchmark_revision_is_another_head(
    clustered_cf_client: AsyncClient,
) -> None:
    first = await post_score(clustered_cf_client, benchmark_revision="r1")
    second = await post_score(clustered_cf_client, benchmark_revision="r2")

    assert first.json()["id"] != second.json()["id"]
    assert first.json()["system_revision_id"] == second.json()["system_revision_id"]


async def test_private_board_cluster_per_submitter_no_registry(
    clustered_cf_client: AsyncClient,
) -> None:
    ana_1 = await post_score(
        clustered_cf_client,
        benchmark_id="priv",
        user=ANA,
        metadata={"system_fingerprint": "sent-by-the-client"},
    )
    ana_2 = await post_score(clustered_cf_client, benchmark_id="priv", user=ANA, score=0.5)
    bruno = await post_score(clustered_cf_client, benchmark_id="priv", user=BRUNO)

    assert ana_2.json()["id"] == ana_1.json()["id"]
    assert ana_2.json()["reported_results_count"] == 2
    assert bruno.json()["id"] != ana_1.json()["id"]
    assert await System.all().count() == 0
    assert await Score.all().count() == 2
    head = await Score.get(id=ana_1.json()["id"])
    assert head.metadata is not None
    # INVARIANT: recomputed by the server from the url4 text; the client value is overwritten.
    assert head.metadata["system_fingerprint"] == Url4Fingerprinter().identify(URL4_A).fingerprint
    assert head.system_revision_id is None


async def test_private_board_ignores_revision_of(clustered_cf_client: AsyncClient) -> None:
    # WHY: a private board never touches the registry (I-N4), so `revision_of` names nothing.
    response = await post_score(
        clustered_cf_client, benchmark_id="priv", user=ANA, revision_of="does-not-exist"
    )

    assert response.status_code == 201
    assert await System.all().count() == 0


async def test_private_board_clusters_by_recomputed_fingerprint_not_by_text(
    clustered_cf_client: AsyncClient,
) -> None:
    # The same system written with different whitespace has the same fingerprint.
    spaced = "( https://model.test/cand-a )!'answer'"
    first = await post_score(clustered_cf_client, benchmark_id="priv", user=ANA)
    second = await post_score(
        clustered_cf_client, benchmark_id="priv", user=ANA, url4_expression=spaced, score=0.5
    )
    other = await post_score(
        clustered_cf_client, benchmark_id="priv", user=ANA, url4_expression=URL4_B, score=0.5
    )

    assert second.json()["id"] == first.json()["id"]
    assert other.json()["id"] != first.json()["id"]


async def test_no_receipt_means_no_publication_row(clustered_cf_client: AsyncClient) -> None:
    response = await post_score(clustered_cf_client)

    assert response.status_code == 201
    assert response.json()["reported_result"]["cache_version"] is None
    assert response.json()["reported_result"]["publication_state"] is None
    assert await CacheVersionPublication.all().count() == 0
    stored = await ReportedResult.get(id=response.json()["reported_result"]["id"])
    assert stored.cache_version_id is None
    assert stored.cache_coverage_status is None


async def test_the_client_cannot_set_the_cache_columns_without_a_receipt(
    clustered_cf_client: AsyncClient,
) -> None:
    response = await post_score(
        clustered_cf_client, metadata={"cache_version_id": str(uuid.uuid4())}
    )

    assert response.json()["reported_result"]["cache_version"] is None


async def test_submit_counts_kind(clustered_cf_client: AsyncClient, clustered_cf_app: Any) -> None:
    await post_score(clustered_cf_client, user=ANA, key="run-1")
    await post_score(clustered_cf_client, user=BRUNO, score=0.5)
    await post_score(clustered_cf_client, user=ANA, key="run-1")

    registry = clustered_cf_app.state.metrics.registry

    def count(kind: str) -> float | None:
        return registry.get_sample_value("scoreboard_submits_total", {"kind": kind})

    assert count("new_head") == 1.0
    assert count("reported_result") == 1.0
    assert count("replay_idempotent") == 1.0
