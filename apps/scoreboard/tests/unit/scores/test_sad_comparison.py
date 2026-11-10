from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from scoreboard.config import Settings
from scoreboard.import_baselines import import_baselines, load_baselines_json
from scoreboard.main import create_app
from scoreboard.scores.models import Baseline, Benchmark

BOARD = "inspect-sad_facts_llms"
REVISION = "c55f043049f958b9"
PAYLOAD = Path(__file__).resolve().parents[3] / "docs/imports/sad-facts-llms.json"


def _rows():
    return load_baselines_json(PAYLOAD.read_text())


async def _board():
    return await Benchmark.create(
        id=BOARD, display_name="SAD Facts: LLMs", revision=REVISION, case_count=249
    )


@pytest.mark.asyncio
async def test_published_sad_import_round_trips_without_duplicate_rows(tortoise_db: None) -> None:
    await _board()
    imported = await import_baselines(_rows())
    repeated = await import_baselines(_rows())
    assert [row.id for row in imported] == [row.id for row in repeated]
    assert all(row.ranking_eligible for row in repeated)
    assert await Baseline.all().count() == 2

    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/leaderboard/{BOARD}")
    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []
    assert [(row["model_name"], row["score"]) for row in body["baselines"]] == [
        ("Claude 3 Opus", 0.857),
        ("Claude 3 Haiku", 0.787),
    ]
    for row in body["baselines"]:
        assert row["ranking_eligible"] is True
        assert row["metric_name"] == "sad_score"
        assert "attached_by" not in row
        assert row["metadata"]["comparison"]["original_score"] == row["score"]
        assert row["source_url"] == _rows()[0].source_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    [
        {"evaluated_case_count": 248},
        {"benchmark_revision": "another-revision"},
        {"question_set_sha256": "0" * 64},
        {"grading_id": "ordinary-correct-incorrect"},
        {
            "original_score": 196,
            "original_unit": "correct_count",
            "conversion": "count_to_fraction",
        },
    ],
)
async def test_sad_incompatible_second_row_rolls_back_batch(
    tortoise_db: None, override: dict
) -> None:
    await _board()
    rows = _rows()
    metadata = deepcopy(rows[1].metadata)
    assert metadata is not None
    metadata["comparison"].update(override)
    rows[1] = rows[1].model_copy(update={"metadata": metadata})
    with pytest.raises(ValueError):
        await import_baselines(rows)
    assert await Baseline.all().count() == 0


@pytest.mark.asyncio
async def test_sad_does_not_accept_plain_accuracy_or_stale_board_scope(tortoise_db: None) -> None:
    board = await _board()
    row = _rows()[0].model_copy(update={"metric_name": "accuracy"})
    with pytest.raises(ValueError):
        await import_baselines([row])
    await Benchmark.filter(id=board.id).update(revision="changed")
    with pytest.raises(ValueError):
        await import_baselines(_rows())
    assert await Baseline.all().count() == 0
