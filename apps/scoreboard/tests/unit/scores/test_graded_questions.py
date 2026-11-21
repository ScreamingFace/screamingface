"""How many of a run's Cases were graded: accepted, stored, exported and served.

FEATURE: a run selects `total_questions` Cases and a Case can fail to be graded (the Candidate call
errors or times out, or the judge gives no readable verdict). `graded_questions` is the count that
did get a grade, so a reader of the leaderboard can see a run that failed on some of its Cases.

INVARIANT: the count is OPTIONAL and null means "not reported", never "none failed". A row without
it, from an older client or from before the column existed, serves and exports exactly what it did
before: the key is absent, not null.

INVARIANT: the count changes nothing about ranking. It is shown beside the score, never read by
the ranking query.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError

from scoreboard.config import Settings
from scoreboard.export_private_submissions import collect_submissions, format_jsonl_bytes
from scoreboard.main import create_app
from scoreboard.scores.models import Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

BENCHMARK = "arc_agi_2"
REV = "rev-1"
CASES = 525


def _submission(
    *, spec_id: str = "fusion-alpha", score: float = 0.6, **fields: object
) -> ScoreSubmission:
    """A full 525-Case submission, plus whatever the test says about its graded Cases."""
    return ScoreSubmission(
        benchmark_id=BENCHMARK,
        spec_id=spec_id,
        url4_expression=f"url4://{spec_id}",
        submitted_by="tester@example.test",
        score=score,
        total_questions=CASES,
        ran_with_providers=["openrouter"],
        metadata={"benchmark_revision": REV},
        **fields,  # type: ignore[arg-type]
    )


# --- The contract --------------------------------------------------------------------------------


def test_a_submission_may_say_how_many_of_its_cases_were_graded() -> None:
    assert _submission(graded_questions=505).graded_questions == 505


def test_a_submission_without_the_count_reads_as_not_reported() -> None:
    """INVARIANT: older clients never send it, and their absence must stay null, not become 0."""
    assert _submission().graded_questions is None


@pytest.mark.parametrize("graded", [0, CASES])
def test_the_count_may_sit_on_either_bound(graded: int) -> None:
    """A run where every Case failed graded 0 of them; a clean run graded all of them."""
    assert _submission(graded_questions=graded).graded_questions == graded


def test_a_negative_count_is_refused() -> None:
    with pytest.raises(ValidationError, match="graded_questions must be non-negative"):
        _submission(graded_questions=-1)


def test_a_count_above_the_selected_cases_is_refused() -> None:
    """INVARIANT: graded Cases are a subset of the selected ones, so the count cannot exceed them.

    Accepting it would let the leaderboard print "530 / 525 graded", a claim no run can make.
    """
    with pytest.raises(ValidationError, match="graded_questions cannot exceed total_questions"):
        _submission(graded_questions=CASES + 1)


@pytest.mark.parametrize("bad", [505.5, "most", [505]])
def test_a_count_that_is_not_a_whole_number_is_refused(bad: object) -> None:
    with pytest.raises(ValidationError):
        _submission(graded_questions=bad)


# --- Storage, receipt and export -----------------------------------------------------------------


@pytest_asyncio.fixture
async def benchmark(tortoise_db: None) -> None:
    await ScoreStore().register_benchmark(
        benchmark_id=BENCHMARK, display_name="ARC-AGI-2", revision=REV, case_count=CASES
    )


@pytest_asyncio.fixture
async def api(benchmark: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_the_count_is_stored_and_on_the_receipt(benchmark: None) -> None:
    outcome = await ScoreStore().submit(_submission(graded_questions=505))

    stored = await Score.get(id=outcome.score.id)
    assert stored.graded_questions == 505
    assert outcome.score.graded_questions == 505


@pytest.mark.asyncio
async def test_the_export_carries_the_count_when_present(benchmark: None) -> None:
    """The private export is how a leaderboard is restored, so a stored column must survive it."""
    await ScoreStore().submit(_submission(graded_questions=505))

    (row,) = map(json.loads, format_jsonl_bytes(await collect_submissions(BENCHMARK)).splitlines())

    assert row["graded_questions"] == 505


@pytest.mark.asyncio
async def test_the_export_omits_an_absent_count(benchmark: None) -> None:
    """INVARIANT: an always-present null key would change the bytes of every export made before
    this field existed, and a certified export could no longer authorise its own purge."""
    await ScoreStore().submit(_submission())

    (row,) = map(json.loads, format_jsonl_bytes(await collect_submissions(BENCHMARK)).splitlines())

    assert "graded_questions" not in row


# --- The leaderboard a reader sees ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_leaderboard_serves_the_count_beside_the_score(api: httpx.AsyncClient) -> None:
    """The whole point: 20 of this run's 525 Cases failed, and the entry now says so."""
    await ScoreStore().submit(_submission(graded_questions=505))

    (entry,) = (await api.get(f"/v1/leaderboard/{BENCHMARK}")).json()["entries"]

    assert (entry["total_questions"], entry["graded_questions"]) == (CASES, 505)


@pytest.mark.asyncio
async def test_the_leaderboard_omits_the_key_for_an_entry_without_a_count(
    api: httpx.AsyncClient,
) -> None:
    """INVARIANT: unknown is ABSENT. A null or 0 here would read as "0 graded" or "none failed"."""
    await ScoreStore().submit(_submission())

    (entry,) = (await api.get(f"/v1/leaderboard/{BENCHMARK}")).json()["entries"]

    assert "graded_questions" not in entry


@pytest.mark.asyncio
async def test_a_partly_graded_full_run_still_ranks_where_its_score_puts_it(
    api: httpx.AsyncClient,
) -> None:
    """INVARIANT: the count is an annotation. It must not move, hide or demote a row, because the
    ranking rule (a run must cover the Benchmark's Case count) is deliberately unchanged."""
    await ScoreStore().submit(_submission(spec_id="solo-clean", score=0.5, graded_questions=CASES))
    await ScoreStore().submit(_submission(spec_id="fusion-partial", score=0.9, graded_questions=1))

    entries = (await api.get(f"/v1/leaderboard/{BENCHMARK}")).json()["entries"]

    assert [(entry["rank"], entry["spec_id"]) for entry in entries] == [
        (1, "fusion-partial"),
        (2, "solo-clean"),
    ]


# --- The submit route ----------------------------------------------------------------------------


def _wire(**fields: object) -> dict[str, object]:
    """The JSON a client posts for a full 525-Case run."""
    return {
        "benchmark_id": BENCHMARK,
        "spec_id": "fusion-alpha",
        "url4_expression": "url4://fusion-alpha",
        "submitted_by": "tester@example.test",
        "score": 0.6,
        "total_questions": CASES,
        "ran_with_providers": ["openrouter"],
        "metadata": {"benchmark_revision": REV},
        **fields,
    }


@pytest.mark.asyncio
async def test_the_submit_route_stores_a_posted_count(api: httpx.AsyncClient) -> None:
    response = await api.post("/v1/scores", json=_wire(graded_questions=505))

    assert response.status_code == 201
    assert response.json()["graded_questions"] == 505


@pytest.mark.asyncio
async def test_the_submit_route_keeps_accepting_a_client_that_sends_no_count(
    api: httpx.AsyncClient,
) -> None:
    """Every SDK released before this field posts exactly this; it must stay a 201."""
    response = await api.post("/v1/scores", json=_wire())

    assert response.status_code == 201
    assert "graded_questions" not in response.json()


@pytest.mark.parametrize("bad", [-1, CASES + 1, 505.5, "most"])
@pytest.mark.asyncio
async def test_the_submit_route_refuses_an_impossible_count_and_stores_nothing(
    api: httpx.AsyncClient, bad: object
) -> None:
    response = await api.post("/v1/scores", json=_wire(graded_questions=bad))

    assert response.status_code == 422
    assert await Score.all().count() == 0
