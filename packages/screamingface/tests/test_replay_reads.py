"""Find the published score a pinned-cache replay is judged against (OME-1613 row 1).

FEATURE: OME-1613 — `sf.evaluate(pinned_cache=…)` and `sf.evaluate(score_id=…)` (spec §2). A
`pinned_cache` replay reads the public lookup by copy id; a `score_id` replay reads the public score
first and falls back to the gated read only when the public read answers 404 (a private score).
STORY: as a researcher, I replay a published run without logging in; as the owner of a private
score, I replay it after logging in.

The board is faked with `httpx.MockTransport`; every assertion is on parsed fields.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import httpx
import pytest
from test_leaderboards import SCORE_ID, _async_client, _score_response, _sync_client

import screamingface as sf
from screamingface._scoreboard.replay_reads import PublishedScore

COPY = "0b1f6d3a-5c0e-4a8e-9a3f-2f6f8f4c7d11"
DIGEST = "ab" * 32
LOOKUP_PATH = f"/v1/public/scores/by-pinned-cache/{COPY}"
PUBLIC_PATH = f"/v1/public/scores/{SCORE_ID}"
GATED_PATH = f"/v1/scores/{SCORE_ID}"


def _lookup(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "score_id": SCORE_ID,
        "benchmark_id": "draco",
        "benchmark_revision": "fixture-revision",
        "url4_expression": "/benchmarks/draco/fixture-revision/run()",
        "answer_seed": 42,
        "score": 0.5,
        "total_questions": 2,
        "case_digest": DIGEST,
        "capture_status": "complete",
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def _captured_score() -> dict[str, object]:
    payload = _score_response()
    payload.update(
        {
            "frozen_copy_id": COPY,
            "capture_status": "complete",
            "case_digest": DIGEST,
            "answer_seed": 7,
            "benchmark_revision": "fixture-revision",
        }
    )
    return payload


def _routes(
    answers: dict[str, httpx.Response], seen: list[str]
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return answers.get(request.url.path, httpx.Response(500))

    return handler


def test_a_pinned_cache_lookup_returns_what_a_replay_needs() -> None:
    seen: list[str] = []
    handler = _routes({LOOKUP_PATH: httpx.Response(200, json=_lookup())}, seen)

    with _sync_client(handler) as client:
        published = client.leaderboards._published_by_pinned_cache(COPY)

    assert seen == [LOOKUP_PATH]
    assert published == PublishedScore(
        score_id=UUID(SCORE_ID),
        pinned_cache=COPY,
        capture_status="complete",
        url4="/benchmarks/draco/fixture-revision/run()",
        answer_seed=42,
        score=0.5,
        total_questions=2,
        benchmark_id="draco",
        benchmark_revision="fixture-revision",
        case_digest=DIGEST,
    )


def test_a_lookup_without_a_seed_means_the_run_had_none() -> None:
    handler = _routes({LOOKUP_PATH: httpx.Response(200, json=_lookup(answer_seed=None))}, [])

    with _sync_client(handler) as client:
        published = client.leaderboards._published_by_pinned_cache(COPY)

    assert published.answer_seed is None


def test_a_zero_seed_is_a_seed() -> None:
    handler = _routes({LOOKUP_PATH: httpx.Response(200, json=_lookup(answer_seed=0))}, [])

    with _sync_client(handler) as client:
        published = client.leaderboards._published_by_pinned_cache(COPY)

    assert published.answer_seed == 0


def test_an_unknown_pinned_cache_names_every_reason_the_board_answers_404() -> None:
    handler = _routes({LOOKUP_PATH: httpx.Response(404, json={"detail": "not found"})}, [])

    with _sync_client(handler) as client, pytest.raises(sf.LeaderboardError) as caught:
        client.leaderboards._published_by_pinned_cache(COPY)

    assert caught.value.code == "unknown_pinned_cache"
    assert caught.value.status == 404


@pytest.mark.parametrize("value", ["not-a-uuid", "0B1F6D3A-5C0E-4A8E-9A3F-2F6F8F4C7D11", ""])
def test_a_malformed_pinned_cache_fails_before_any_request(value: str) -> None:
    seen: list[str] = []

    with _sync_client(_routes({}, seen)) as client, pytest.raises(ValueError):
        client.leaderboards._published_by_pinned_cache(value)

    assert seen == []


def test_a_score_id_reads_the_public_score_first() -> None:
    seen: list[str] = []
    handler = _routes({PUBLIC_PATH: httpx.Response(200, json=_captured_score())}, seen)

    with _sync_client(handler) as client:
        published = client.leaderboards._published_score(SCORE_ID)

    assert seen == [PUBLIC_PATH]
    assert published.pinned_cache == COPY
    assert published.answer_seed == 7
    assert published.case_digest == DIGEST
    assert published.benchmark_revision == "fixture-revision"


def test_a_private_score_falls_back_to_the_gated_read() -> None:
    seen: list[str] = []
    handler = _routes(
        {
            PUBLIC_PATH: httpx.Response(404, json={"detail": "not found"}),
            GATED_PATH: httpx.Response(200, json=_captured_score()),
        },
        seen,
    )

    with _sync_client(handler) as client:
        published = client.leaderboards._published_score(SCORE_ID)

    assert seen == [PUBLIC_PATH, GATED_PATH]
    assert published.score_id == UUID(SCORE_ID)


def test_a_score_neither_read_finds_is_unknown() -> None:
    handler = _routes(
        {
            PUBLIC_PATH: httpx.Response(404, json={"detail": "not found"}),
            GATED_PATH: httpx.Response(404, json={"detail": "not found"}),
        },
        [],
    )

    with _sync_client(handler) as client, pytest.raises(sf.LeaderboardError) as caught:
        client.leaderboards._published_score(SCORE_ID)

    assert caught.value.code == "unknown_score"


def test_a_public_read_error_that_is_not_404_does_not_fall_back() -> None:
    seen: list[str] = []
    handler = _routes({PUBLIC_PATH: httpx.Response(503)}, seen)

    with _sync_client(handler) as client, pytest.raises(sf.LeaderboardError):
        client.leaderboards._published_score(SCORE_ID)

    assert seen == [PUBLIC_PATH]


@pytest.mark.asyncio
async def test_the_async_reads_match_the_sync_reads() -> None:
    seen: list[str] = []
    handler = _routes(
        {
            LOOKUP_PATH: httpx.Response(200, json=_lookup()),
            PUBLIC_PATH: httpx.Response(404, json={"detail": "not found"}),
            GATED_PATH: httpx.Response(200, json=_captured_score()),
        },
        seen,
    )

    async with _async_client(handler) as client:
        by_copy = await client.leaderboards._published_by_pinned_cache(COPY)
        by_score = await client.leaderboards._published_score(SCORE_ID)

    assert seen == [LOOKUP_PATH, PUBLIC_PATH, GATED_PATH]
    assert by_copy.answer_seed == 42
    assert by_score.pinned_cache == COPY


# --- review fix 1: the lookup is decoded as strictly as a score read ---------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"case_digest": "AB" * 32},
        {"case_digest": "ab" * 31},
        {"case_digest": 7},
        {"capture_status": None},
        {"capture_status": "pending"},
        {"score_id": "not-a-uuid"},
    ],
    ids=[
        "upper-digest",
        "short-digest",
        "number-digest",
        "digest-without-status",
        "unknown-status",
        "bad-score-id",
    ],
)
def test_a_malformed_lookup_is_a_scoreboard_contract_error(overrides: dict[str, object]) -> None:
    lookup = _lookup()
    lookup.update(overrides)
    payload = {key: value for key, value in lookup.items() if value is not None}
    handler = _routes({LOOKUP_PATH: httpx.Response(200, json=payload)}, [])

    with _sync_client(handler) as client, pytest.raises(sf.LeaderboardError) as caught:
        client.leaderboards._published_by_pinned_cache(COPY)

    assert caught.value.code == "invalid_leaderboard"
