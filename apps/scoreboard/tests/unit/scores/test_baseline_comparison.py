from __future__ import annotations

from copy import deepcopy
from typing import Any

import httpx
import pytest

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import Baseline, Benchmark
from scoreboard.scores.schemas import BaselineImportRow

BOARD = "inspect-agieval_sat_en"
REVISION = "092ea478f523193d"
QUESTIONS = "33fe87b32ff16ae7ba52b27bb398190b082253b3617a3eb9737005262ba12dd4"


def _review(**overrides: Any) -> dict[str, Any]:
    return {
        "policy_version": "1",
        "benchmark_revision": REVISION,
        "question_set_sha256": QUESTIONS,
        "grading_id": "inspect-ai-0.3.263-choice",
        "evaluated_case_count": 206,
        "original_score": 75.0,
        "original_unit": "percent",
        "conversion": "percent_to_fraction",
        "reviewed_at": "2026-11-04T10:00:00Z",
        "prompt_note": "Different instructions; the same answer marker and grading rules.",
        "evidence": {
            key: "https://example.org/report/" + key
            for key in ("questions", "grading", "coverage", "units")
        },
        **overrides,
    }


def _row(**overrides: Any) -> BaselineImportRow:
    return BaselineImportRow.model_validate(
        {
            "benchmark_id": BOARD,
            "model_name": "Example",
            "score": 0.75,
            "source": "paper",
            "source_url": "https://example.org/report",
            "metric_name": "accuracy",
            "observed_at": "2026-11-03T10:00:00Z",
            "attached_by": "internal-reviewer",
            "metadata": {"comparison": _review()},
            **overrides,
        }
    )


async def _board(**overrides: Any) -> Benchmark:
    return await Benchmark.create(
        **{
            "id": BOARD,
            "display_name": "SAT-English",
            "revision": REVISION,
            "case_count": 206,
            **overrides,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["public", "private"])
async def test_verified_converted_result_is_eligible_without_leaking_reviewer(
    tortoise_db: None,
    visibility: str,
) -> None:
    await _board(visibility=visibility)
    result = await BaselineStore().import_baseline(_row())
    assert result.ranking_eligible is True
    assert result.metadata == {"comparison": _review()}
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/leaderboard/{BOARD}")
    assert response.status_code == 200
    baseline = response.json()["baselines"][0]
    assert baseline["ranking_eligible"] is True
    assert "attached_by" not in baseline
    assert baseline["metadata"]["comparison"]["original_score"] == 75.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata", [None, {}, {"strictly_comparable": True}, {"ranking_eligible": True}]
)
async def test_legacy_and_unreviewed_observations_stay_stored_but_unranked(
    tortoise_db: None,
    metadata: Any,
) -> None:
    await _board()
    row = await BaselineStore().import_baseline(_row(metadata=metadata))
    assert row.ranking_eligible is False
    assert (await BaselineStore().list_baselines(BOARD))[0].ranking_eligible is False
    assert await Baseline.filter(id=row.id).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    [
        {"benchmark_revision": "different"},
        {"question_set_sha256": "0" * 64},
        {"grading_id": "first-capital-letter"},
        {"evaluated_case_count": 100},
        {"evaluated_case_count": 207},
        {"evaluated_case_count": True},
        {"original_unit": "elo"},
        {"conversion": "guess"},
        {"original_score": 74.9},
        {"original_score": True},
        {"original_score": "75"},
        {"original_score": float("nan")},
        {"prompt_note": " "},
        {"reviewed_at": "2026-11-04"},
        {"reviewed_at": "2999-01-01T00:00:00Z"},
        {"policy_version": "2"},
        {"evidence": {}},
        {
            "evidence": {
                key: "javascript:alert(1)" for key in ("questions", "grading", "coverage", "units")
            }
        },
    ],
)
async def test_invalid_review_is_rejected_before_writing(tortoise_db: None, override: dict) -> None:
    await _board()
    with pytest.raises(ValueError):
        await BaselineStore().import_baseline(_row(metadata={"comparison": _review(**override)}))
    assert await Baseline.all().count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    [
        {"metric_name": "elo"},
        {"metric_name": None},
        {"source_url": None},
        {"source_url": "https://"},
        {"observed_at": None},
        {"attached_by": None},
        {"observed_at": "2026-11-05T00:00:00Z"},
    ],
)
async def test_review_needs_complete_compatible_observation(
    tortoise_db: None, override: dict
) -> None:
    await _board()
    with pytest.raises(ValueError):
        await BaselineStore().import_baseline(_row(**override))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "review"),
    [
        (0.932, {"original_score": 93.2}),
        (0.704, {"original_score": 70.4}),
        (0.0, {"original_score": 0}),
        (1.0, {"original_score": 100}),
        (0.75, {"original_score": 0.75, "original_unit": "fraction", "conversion": "identity"}),
        (
            186 / 206,
            {
                "original_score": 186,
                "original_unit": "correct_count",
                "conversion": "count_to_fraction",
            },
        ),
    ],
)
async def test_exact_documented_conversions(tortoise_db: None, score: float, review: dict) -> None:
    await _board()
    result = await BaselineStore().import_baseline(
        _row(score=score, metadata={"comparison": _review(**review)})
    )
    assert result.ranking_eligible is True
    assert result.score == score


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "review"),
    [
        (-0.01, {"original_score": -1}),
        (1.01, {"original_score": 101}),
        (0.75, {"original_score": 0.75, "original_unit": "percent", "conversion": "identity"}),
        (
            0.75,
            {
                "original_score": 154.5,
                "original_unit": "correct_count",
                "conversion": "count_to_fraction",
            },
        ),
    ],
)
async def test_invalid_ranges_and_conversion_claims(
    tortoise_db: None, score: float, review: dict
) -> None:
    await _board()
    with pytest.raises(ValueError):
        await BaselineStore().import_baseline(
            _row(score=score, metadata={"comparison": _review(**review)})
        )


@pytest.mark.asyncio
async def test_current_scope_and_replaced_observation_revoke_eligibility(tortoise_db: None) -> None:
    board = await _board()
    store = BaselineStore()
    original = await store.import_baseline(_row())
    for changed in ({"revision": "new"}, {"case_count": 205}, {"revision": None}):
        await Benchmark.filter(id=board.id).update(revision=REVISION, case_count=206)
        await Benchmark.filter(id=board.id).update(**changed)
        assert (await store.list_baselines(BOARD))[0].ranking_eligible is False
    await Benchmark.filter(id=board.id).update(revision=REVISION, case_count=206)
    assert (await store.list_baselines(BOARD))[0].ranking_eligible is True
    replaced = await store.import_baseline(_row(score=0.8, metadata=None))
    assert replaced.id == original.id
    assert replaced.ranking_eligible is False


@pytest.mark.asyncio
async def test_malformed_stored_review_and_changed_score_fail_closed(tortoise_db: None) -> None:
    await _board()
    store = BaselineStore()
    row = await store.import_baseline(_row())
    for metadata in ({"comparison": None}, {"comparison": {}}, {"comparison": "approved"}):
        await Baseline.filter(id=row.id).update(metadata=metadata)
        assert (await store.list_baselines(BOARD))[0].ranking_eligible is False
    await Baseline.filter(id=row.id).update(metadata={"comparison": _review()}, score=0.99)
    assert (await store.list_baselines(BOARD))[0].ranking_eligible is False


@pytest.mark.asyncio
async def test_unknown_profile_and_failed_batch_do_not_publish_review(tortoise_db: None) -> None:
    await _board()
    await Benchmark.create(id="unknown", display_name="Unknown", revision=REVISION, case_count=206)
    store = BaselineStore()
    with pytest.raises(ValueError):
        await store.import_many([_row(), _row(benchmark_id="unknown")])
    assert await Baseline.all().count() == 0
    first = await store.import_baseline(_row())
    with pytest.raises(ValueError):
        await store.import_many([_row(score=0.8, metadata=None), _row(benchmark_id="unknown")])
    assert (await store.list_baselines(BOARD))[0] == first


@pytest.mark.asyncio
async def test_known_incompatibility_cannot_be_overridden_by_a_review(tortoise_db: None) -> None:
    await _board()
    metadata = deepcopy(_row().metadata)
    assert metadata is not None
    metadata["strictly_comparable"] = False
    with pytest.raises(ValueError):
        await BaselineStore().import_baseline(_row(metadata=metadata))


@pytest.mark.asyncio
async def test_scope_change_during_response_cannot_publish_stale_approval(
    tortoise_db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _board()
    await BaselineStore().import_baseline(_row())
    original = BaselineStore.list_baselines

    async def change_after_read(store: BaselineStore, board_id: str):
        rows = await original(store, board_id)
        assert rows[0].ranking_eligible is True
        await Benchmark.filter(id=board_id).update(revision="new-revision")
        return rows

    monkeypatch.setattr(BaselineStore, "list_baselines", change_after_read)
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/v1/leaderboard/{BOARD}")
    assert response.status_code == 200
    assert response.json()["benchmark"]["revision"] == "new-revision"
    assert response.json()["baselines"][0]["ranking_eligible"] is False


@pytest.mark.asyncio
async def test_fraction_to_percent_requires_a_percent_board_profile(
    tortoise_db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace
    from decimal import Decimal

    from scoreboard.scores.comparison_profiles import PROFILES

    await _board()
    monkeypatch.setitem(
        PROFILES, BOARD, replace(PROFILES[BOARD], unit="percent", maximum=Decimal(100))
    )
    review = _review(
        original_score=0.932, original_unit="fraction", conversion="fraction_to_percent"
    )
    result = await BaselineStore().import_baseline(
        _row(score=93.2, metadata={"comparison": review})
    )
    assert result.ranking_eligible is True
    with pytest.raises(ValueError):
        await BaselineStore().import_baseline(
            _row(
                score=932,
                metadata={
                    "comparison": {
                        **review,
                        "original_score": 9.32,
                    }
                },
            )
        )


def test_importer_does_not_accept_a_client_supplied_eligibility_flag() -> None:
    with pytest.raises(ValueError):
        _row(ranking_eligible=True)
