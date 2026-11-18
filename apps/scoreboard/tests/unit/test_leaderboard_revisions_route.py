"""The leaderboard serves any revision a benchmark has had, not only the current one (OME-1708).

FEATURE: the revision selector. `GET /v1/leaderboard/{id}/revisions` lists the revisions, and
`?revision=` on the board and frontier scopes them to one. Without the parameter every response is
exactly what it was before.

STORY: as a researcher, after MMLU-Pro's revision moves, I pick the previous revision and see its
complete runs ranked against that revision's own Case count.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.schemas import ClientInfo, ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

_OLD, _NEW = "rev-old", "rev-new"


@pytest_asyncio.fixture
async def async_client(tortoise_db: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _run(
    spec_id: str, score: float, *, revision: str, total: int = 100, cost: str = "1.000000"
) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id="mmlu_pro",
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/mmlu_pro/{revision}/{spec_id}/{score}/{total}",
        submitted_by="tester",
        score=score,
        total_questions=total,
        correct_questions=int(score * total),
        ran_with_providers=["openai"],
        run_cost_usd=Decimal(cost),
        run_cost_status="complete",
        ran_at_local=datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
        client=ClientInfo(name="scoreboard-test", version="0.1.0", platform="test"),
        benchmark_revision=revision,
    )


async def _board_with_a_bump(store: ScoreStore) -> None:
    """MMLU-Pro at rev-old (100 Cases) with two full runs and a smoke run, then bumped.

    Under rev-old the cheaper `opus` run sits on the cost/score frontier beside `trio`, so the old
    frontier has two members and the new one (a single run) has one.
    """

    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision=_OLD, case_count=100)
    await store.submit(_run("trio", 0.93, revision=_OLD))
    await store.submit(_run("opus", 0.91, revision=_OLD, cost="0.500000"))
    await store.submit(_run("smoke", 1.0, revision=_OLD, total=10))
    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision=_NEW, case_count=100)
    await store.submit(_run("trio", 0.95, revision=_NEW))


async def test_revisions_are_listed_newest_first_with_their_complete_result_counts(
    async_client: httpx.AsyncClient,
) -> None:
    await _board_with_a_bump(ScoreStore())

    response = await async_client.get("/v1/leaderboard/mmlu_pro/revisions")

    assert response.status_code == 200
    revisions = response.json()["revisions"]
    assert [
        (r["revision"], r["current"], r["case_count"], r["result_count"]) for r in revisions
    ] == [(_NEW, True, 100, 1), (_OLD, False, 100, 2)]
    # The old revision ran until the new one was first seen; the current one is open-ended.
    assert revisions[1]["until"] == revisions[0]["first_seen_at"]
    assert revisions[0]["until"] is None
    assert [r["first_seen_inferred"] for r in revisions] == [False, False]
    assert [r["case_count_inferred"] for r in revisions] == [False, False]


async def test_the_board_ranks_a_past_revision_by_its_own_case_count(
    async_client: httpx.AsyncClient,
) -> None:
    # INVARIANT (OME-1056 within the selected revision): the 10-Case smoke run never ranks.
    await _board_with_a_bump(ScoreStore())

    response = await async_client.get("/v1/leaderboard/mmlu_pro", params={"revision": _OLD})

    assert response.status_code == 200
    body = response.json()
    assert [entry["spec_id"] for entry in body["entries"]] == ["trio", "opus"]
    assert (body["benchmark"]["revision"], body["benchmark"]["case_count"]) == (_OLD, 100)


async def test_without_a_revision_the_board_is_the_current_one(
    async_client: httpx.AsyncClient,
) -> None:
    await _board_with_a_bump(ScoreStore())

    plain = await async_client.get("/v1/leaderboard/mmlu_pro")
    explicit = await async_client.get("/v1/leaderboard/mmlu_pro", params={"revision": _NEW})

    assert [entry["spec_id"] for entry in plain.json()["entries"]] == ["trio"]
    assert plain.json()["benchmark"]["revision"] == _NEW
    assert explicit.json() == plain.json()


async def test_the_frontier_follows_the_chosen_revision(async_client: httpx.AsyncClient) -> None:
    await _board_with_a_bump(ScoreStore())

    old = await async_client.get("/v1/leaderboard/mmlu_pro/frontier", params={"revision": _OLD})
    plain = await async_client.get("/v1/leaderboard/mmlu_pro/frontier")
    current = await async_client.get("/v1/leaderboard/mmlu_pro/frontier", params={"revision": _NEW})

    assert old.status_code == 200
    assert (old.json()["frontier_size"], plain.json()["frontier_size"]) == (2, 1)
    assert current.json() == plain.json()


@pytest.mark.parametrize("path", ["/v1/leaderboard/mmlu_pro", "/v1/leaderboard/mmlu_pro/frontier"])
async def test_an_unknown_revision_is_404(async_client: httpx.AsyncClient, path: str) -> None:
    await _board_with_a_bump(ScoreStore())

    response = await async_client.get(path, params={"revision": "rev-never"})

    assert response.status_code == 404


async def test_a_private_board_does_not_publish_its_revisions(
    async_client: httpx.AsyncClient,
) -> None:
    # WHY: result counts per revision describe every participant, like the frontier, which a
    # private board also withholds (OME-894).
    store = ScoreStore()
    await _board_with_a_bump(store)
    await store.set_visibility("mmlu_pro", "private")

    response = await async_client.get("/v1/leaderboard/mmlu_pro/revisions")

    assert response.status_code == 404


async def test_revisions_of_an_unknown_benchmark_is_404(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/v1/leaderboard/nope/revisions")

    assert response.status_code == 404


async def test_history_keeps_every_run_with_its_revision(async_client: httpx.AsyncClient) -> None:
    # The history page's Revision column reads each row's own revision; which one is current
    # comes from /revisions (`current`), so the history response itself is unchanged.
    await _board_with_a_bump(ScoreStore())

    history = await async_client.get("/v1/leaderboard/mmlu_pro/trio/history")
    revisions = await async_client.get("/v1/leaderboard/mmlu_pro/revisions")

    assert [row["benchmark_revision"] for row in history.json()["submissions"]] == [_NEW, _OLD]
    assert [r["revision"] for r in revisions.json()["revisions"] if r["current"]] == [_NEW]
