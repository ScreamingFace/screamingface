"""How many Cases a run graded, carried from the result to the leaderboard submission.

A run selects N Cases and a Case can fail to be graded (the Candidate call errors or times out, or
the judge gives no readable verdict). The SDK already shows the submitter "1 / 2 graded" and warns
"Partial submission"; before this field none of it reached the leaderboard, which received only
the selected-Case total, failed Cases included.

INVARIANT: `graded_questions` is sent only when at least one Case went ungraded. A fully graded run
sends the payload it always sent, so a leaderboard that predates the field (it forbids unknown
keys) refuses only the partial runs rather than every submission.
"""

from __future__ import annotations

import json

import httpx
import pytest
from test_partial_submission_notice import _async_client, _candidate, _client, _score_response

import screamingface as sf
from screamingface._scoreboard.leaderboards import _submission


def test_a_run_with_an_ungraded_case_sends_how_many_were_graded() -> None:
    """Three Cases selected, one failed in grading: the leaderboard must hear 2 of 3."""
    payload = _submission(_candidate(benchmark_case_count=3, case_scores=(1.0, None, 0.0)))

    assert (payload["total_questions"], payload["graded_questions"]) == (3, 2)


def test_a_fully_graded_run_sends_no_count() -> None:
    """INVARIANT: omitted, never sent as null or as the total, so this payload is byte-for-byte
    what a leaderboard that predates the field already accepts."""
    payload = _submission(_candidate(benchmark_case_count=2, case_scores=(1.0, 0.0)))

    assert "graded_questions" not in payload


def test_the_count_is_the_one_the_results_coverage_is_made_of() -> None:
    """INVARIANT: one definition of "graded". The count sent must reproduce the result's own
    `coverage`, so the leaderboard and the local report cannot disagree about the same run."""
    result = _candidate(benchmark_case_count=4, case_scores=(1.0, None, 0.0, None))
    payload = _submission(result)

    graded = payload["graded_questions"]
    total = payload["total_questions"]
    assert isinstance(graded, int) and isinstance(total, int)
    assert round(graded / total, 4) == result.coverage == 0.5


def test_the_count_reaches_the_wire_on_a_real_submit() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    with _client(handler) as client, pytest.warns(sf.EvaluationWarning):
        client.leaderboards.submit(_candidate(benchmark_case_count=2, case_scores=(1.0, None)))

    assert json.loads(seen[-1].content)["graded_questions"] == 1


@pytest.mark.asyncio
async def test_the_async_submit_sends_the_count_too() -> None:
    """Sync and async share one payload builder; this keeps that true."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    async with _async_client(handler) as client:
        with pytest.warns(sf.EvaluationWarning):
            await client.leaderboards.submit(
                _candidate(benchmark_case_count=2, case_scores=(1.0, None))
            )

    assert json.loads(seen[-1].content)["graded_questions"] == 1
