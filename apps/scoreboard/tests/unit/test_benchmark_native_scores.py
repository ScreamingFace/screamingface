"""Cross-stack contract tests for benchmark-native Leaderboard scores (OME-866).

FEATURE: the Scoreboard accepts, stores and ranks the exact primary score an Engine
Benchmark produced — fractional (DRACO), negative (HealthBench) or binary-derived
(IFEval) — without recomputing, normalizing or bounding it.

INVARIANT: the Engine-side Benchmark is the sole scoring authority. These tests submit
the REAL Client payload shapes for all three registered Benchmarks and assert the score
round-trips byte-identical; any Scoreboard-side reinterpretation is a defect.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import _content_hash

pytestmark = pytest.mark.asyncio

# The realistic score shape per registered Benchmark, from OME-866:
# IFEval stays binary-derived, DRACO is weighted-fractional, HealthBench worst-30
# reports an unclipped mean that goes below zero for every serious baseline.
BENCHMARK_SCORES = {
    "ifeval": 0.5,
    "draco": 0.399,
    "healthbench_worst30": -1.143,
}


def _native_payload(benchmark_id: str, score: float, **overrides: Any) -> dict[str, Any]:
    """The exact wire shape the Client sends after OME-866 — no correct_questions."""
    payload: dict[str, Any] = {
        "version": 1,
        "benchmark_id": benchmark_id,
        "spec_id": "fusion/native",
        "url4_expression": f"url4://benchmark/{benchmark_id}",
        "submitted_by": "tester",
        "score": score,
        "total_questions": 10,
        "ran_with_providers": ["openrouter"],
        "run_cost_usd": "2.500000",
        "ran_at_local": "2026-08-18T09:00:00+00:00",
        "client": {"name": "screamingface", "version": "0.3.0", "platform": "darwin"},
        "metadata": {"benchmark_revision": "rev-1", "run_id": "run-native"},
    }
    payload.update(overrides)
    return payload


@pytest_asyncio.fixture
async def app_with_registered_benchmarks(tortoise_db: None) -> FastAPI:
    settings = Settings(database_url="sqlite://:memory:", cors_origins=[])
    app = create_app(settings)
    for benchmark_id in BENCHMARK_SCORES:
        await Benchmark.create(
            id=benchmark_id,
            display_name=benchmark_id,
            description="Fixture benchmark",
            dataset_url=None,
            revision="rev-1",
        )
    return app


@pytest_asyncio.fixture
async def native_client(
    app_with_registered_benchmarks: FastAPI,
) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app_with_registered_benchmarks),
        base_url="http://test",
    ) as client:
        yield client


# --- schema: the generic score contract ---------------------------------------------


@pytest.mark.parametrize("score", [0.5, 0.399, -1.143, 3.75])
async def test_score_submission_accepts_any_finite_score(score: float) -> None:
    submission = ScoreSubmission.model_validate(_native_payload("draco", score))
    assert submission.score == score


async def test_score_submission_needs_no_correct_questions() -> None:
    submission = ScoreSubmission.model_validate(_native_payload("draco", 0.399))
    assert submission.correct_questions is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
async def test_score_submission_rejects_non_finite_scores(bad: float) -> None:
    with pytest.raises(ValidationError):
        ScoreSubmission.model_validate(_native_payload("draco", bad))


async def test_score_submission_rejects_a_missing_score() -> None:
    payload = _native_payload("draco", 0.399)
    del payload["score"]
    with pytest.raises(ValidationError):
        ScoreSubmission.model_validate(payload)


@pytest.mark.parametrize("bad", [True, "0.399"])
async def test_score_submission_rejects_non_number_scores(bad: object) -> None:
    # WHY strict: JSON true and numeric strings must not coerce into a
    # plausible-looking score (the BaselineImportRow lesson, applied to the wire).
    payload = _native_payload("draco", 0.0)
    payload["score"] = bad
    with pytest.raises(ValidationError):
        ScoreSubmission.model_validate(payload)


# --- route: the real payload round-trips unchanged for all three Benchmarks ----------


@pytest.mark.parametrize(("benchmark_id", "score"), sorted(BENCHMARK_SCORES.items()))
async def test_native_scores_submit_and_round_trip_unchanged(
    native_client: AsyncClient, benchmark_id: str, score: float
) -> None:
    response = await native_client.post("/v1/scores", json=_native_payload(benchmark_id, score))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["score"] == score
    assert body["benchmark_id"] == benchmark_id

    fetched = await native_client.get(f"/v1/scores/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["score"] == score


async def test_the_wire_rejects_the_old_accuracy_field(native_client: AsyncClient) -> None:
    # INVARIANT: the interface is unreleased — no legacy aliases, no dual wire formats.
    payload = _native_payload("draco", 0.399)
    payload["accuracy"] = payload.pop("score")
    response = await native_client.post("/v1/scores", json=payload)
    assert response.status_code == 422


# --- ranking: higher score is better, whatever the range -----------------------------


async def test_leaderboard_ranks_mixed_and_negative_scores_descending(
    native_client: AsyncClient,
) -> None:
    scores = {"spec/low": -1.143, "spec/mid": -0.2, "spec/high": 0.399}
    for spec_id, score in scores.items():
        response = await native_client.post(
            "/v1/scores",
            json=_native_payload("healthbench_worst30", score, spec_id=spec_id),
        )
        assert response.status_code == 201, response.text

    board = await native_client.get("/v1/leaderboard/healthbench_worst30")
    assert board.status_code == 200
    entries = board.json()["entries"]
    assert [entry["spec_id"] for entry in entries] == ["spec/high", "spec/mid", "spec/low"]
    assert [entry["score"] for entry in entries] == [0.399, -0.2, -1.143]
    assert [entry["rank"] for entry in entries] == [1, 2, 3]


# --- dedup identity: the submitted score IS the result identity ----------------------


async def test_content_hash_keys_on_the_submitted_score() -> None:
    first = ScoreSubmission.model_validate(_native_payload("draco", 0.399))
    same = ScoreSubmission.model_validate(_native_payload("draco", 0.399))
    different = ScoreSubmission.model_validate(_native_payload("draco", 0.4))

    assert _content_hash(first) == _content_hash(same)
    assert _content_hash(first) != _content_hash(different)


async def test_a_null_score_is_rejected_not_treated_as_unranked(
    native_client: AsyncClient,
) -> None:
    # INVARIANT: "unrankable" (CandidateResult.score=None) is a CLIENT-side state — the
    # client refuses to submit it. A null reaching the wire is therefore always a bug,
    # never a request to store an unranked row.
    payload = _native_payload("draco", 0.399)
    payload["score"] = None
    response = await native_client.post("/v1/scores", json=payload)
    assert response.status_code == 422


async def test_an_integer_json_score_is_accepted_as_its_float_value(
    native_client: AsyncClient,
) -> None:
    # WHY: strict float rejects Python ints but accepts JSON integer literals (JSON has
    # one number type). A benchmark whose native score lands exactly on 1 serializes as
    # `1`, and that must not 422 a legitimate submission.
    payload = _native_payload("ifeval", 0.0)
    payload["score"] = 1
    response = await native_client.post("/v1/scores", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["score"] == 1.0
