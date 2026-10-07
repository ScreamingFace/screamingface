"""A submission carries the cache version and the answer seed (E14 B5, cv C4, C13, K4, K8).

FEATURE: OME-1307 — `submit` sends `cache_revision`, `reproducible` and `answer_seed` when the run
has them, and `get_score` reads them back, with the reproduction count, from the board.
STORY: as a researcher who submits a score, the board stores which cache version produced it, so
anyone can replay that exact run. A run without cache data still submits to a board that predates
the fields, because the Client omits what it does not know.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from test_leaderboards import (
    SCORE_ID,
    _async_client,
    _candidate_result,
    _score_response,
    _sync_client,
)

import screamingface as sf
from screamingface._scoreboard.leaderboards import _submission

_LABEL = "cr-0123456789ab"
_FIELDS = ("cache_revision", "reproducible", "answer_seed")


def _result(**fields: object) -> sf.CandidateResult:
    base = _candidate_result()
    return sf.CandidateResult(
        benchmark=base.benchmark,
        run_id=base.run_id,
        started_at=base.started_at,
        completed_at=base.completed_at,
        name=base.name,
        kind=base.kind,
        url4=base.url4,
        models=base.models,
        operations=base.operations,
        score=base.score,
        coverage=base.coverage,
        metrics=dict(base.metrics),
        cases=base.cases,
        members=base.members,
        failures=base.failures,
        usage=base.usage,
        **fields,  # type: ignore[arg-type]
    )


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.read())


# --- TDD #15: submit sends the fields when present, else omits them -------------------------------


def test_the_submission_sends_the_cache_version_and_the_answer_seed() -> None:
    payload = _submission(_result(cache_revision=_LABEL, reproducible="complete", answer_seed=7))

    assert payload["cache_revision"] == _LABEL
    assert payload["reproducible"] == "complete"
    assert payload["answer_seed"] == 7


def test_the_submission_omits_every_field_the_run_does_not_have() -> None:
    # INVARIANT (cv C13): omitted, never null, so a board that predates the fields still accepts a
    # run with no cache data.
    payload = _submission(_result())

    assert not [name for name in _FIELDS if name in payload]


def test_a_partial_run_sends_its_status_without_a_revision() -> None:
    payload = _submission(_result(reproducible="partial"))

    assert payload["reproducible"] == "partial"
    assert "cache_revision" not in payload


def test_a_zero_answer_seed_is_sent() -> None:
    # 0 is a sitting. Only None means "no seed".
    assert _submission(_result(answer_seed=0))["answer_seed"] == 0


def test_submit_posts_the_fields_to_the_board() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=_score_response())

    with _sync_client(handler) as client:
        client.leaderboards.submit(
            _result(cache_revision=_LABEL, reproducible="complete", answer_seed=7)
        )

    assert _body(seen[0])["cache_revision"] == _LABEL


# --- K8: get_score reads the board's fields -------------------------------------------------------


def _reproduced_response(**overrides: object) -> dict[str, object]:
    return {
        **_score_response(),
        "benchmark_revision": "fixture-revision",
        "cache_revision": _LABEL,
        "reproducible": "complete",
        "answer_seed": 7,
        "reproduction_count": 3,
        "last_reproduced_at": "2026-10-07T09:00:00Z",
        **overrides,
    }


def test_get_score_reads_the_cache_version_and_the_reproductions() -> None:
    with _sync_client(lambda _: httpx.Response(200, json=_reproduced_response())) as client:
        score = client.leaderboards.get_score(SCORE_ID)

    assert score.cache_revision == _LABEL
    assert score.reproducible == "complete"
    assert score.answer_seed == 7
    assert score.reproduction_count == 3
    assert score.last_reproduced_at == datetime(2026, 10, 7, 9, tzinfo=UTC)
    # The revision of the benchmark the score ran on, from the board's top-level field.
    assert score.benchmark_revision == "fixture-revision"


def test_an_older_board_leaves_the_new_fields_absent() -> None:
    # INVARIANT (K8): absent reads as None, and an absent count reads as 0.
    with _sync_client(lambda _: httpx.Response(200, json=_score_response())) as client:
        score = client.leaderboards.get_score(SCORE_ID)

    assert score.cache_revision is None
    assert score.reproducible is None
    assert score.answer_seed is None
    assert score.reproduction_count == 0
    assert score.last_reproduced_at is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"reproducible": "maybe"},
        {"cache_revision": 7},
        {"answer_seed": "7"},
        {"reproduction_count": -1},
        {"reproduction_count": "3"},
        {"last_reproduced_at": "yesterday"},
    ],
)
def test_a_malformed_cache_version_field_is_a_contract_error(
    overrides: dict[str, object],
) -> None:
    handler = lambda _: httpx.Response(200, json=_reproduced_response(**overrides))  # noqa: E731

    with _sync_client(handler) as client, pytest.raises(sf.LeaderboardError):
        client.leaderboards.get_score(SCORE_ID)


@pytest.mark.asyncio
async def test_the_async_client_reads_the_same_fields() -> None:
    async with _async_client(lambda _: httpx.Response(200, json=_reproduced_response())) as client:
        score = await client.leaderboards.get_score(SCORE_ID)

    assert (score.cache_revision, score.reproduction_count) == (_LABEL, 3)
