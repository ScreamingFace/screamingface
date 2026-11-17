"""The result-returning faces feed the dict faces: the model is what the dict is dumped from."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from test_shared_grading_aggregation import _envelope, _grading, _Hook, _path, _selected, mean_score

from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.contract import CandidateResult
from screamingface_engine.benchmarks.shared_grading.incremental import Scoring


def _kwargs(selected: Any) -> dict[str, Any]:
    return dict(
        benchmark_id="test-benchmark",
        benchmark_revision="rev",
        selected_cases=selected,
        grading_material=lambda case_id: (5, -3),
        scorer=mean_score,
    )


RAW = json.dumps([_envelope(1, _grading(1)), _envelope(2, _grading(2))])


@pytest.mark.asyncio
async def test_aggregate_result_async_is_the_model_the_dict_face_dumps():
    model = await _path(_Hook()).aggregate_result_async(RAW, **_kwargs(_selected(1, 2, 3)))

    assert isinstance(model, CandidateResult)
    assert model.as_payload() == await _path(_Hook()).aggregate_async(
        RAW, **_kwargs(_selected(1, 2, 3))
    )


def test_the_sync_faces_agree():
    assert _path(_Hook()).aggregate_result(RAW, **_kwargs(_selected(1, 2))).as_payload() == (
        _path(_Hook()).aggregate(RAW, **_kwargs(_selected(1, 2)))
    )


def _scoring() -> Scoring:
    return Scoring(
        _path(_Hook()),
        "board",
        "v1",
        _selected(1, 2),
        lambda _: (5, -3),
        lambda cases: CandidateScore(score=0.5, metrics={}),
    )


@pytest.mark.asyncio
async def test_scoring_finish_result_is_what_finish_dumps():
    assert (await _scoring().finish_result("[]")).as_payload() == await _scoring().finish("[]")


def test_scoring_aggregate_result_is_what_aggregate_dumps():
    assert _scoring().aggregate_result(RAW).as_payload() == _scoring().aggregate(RAW)


@pytest.mark.asyncio
async def test_the_aggregate_logs_three_memory_points(caplog):
    caplog.set_level(logging.INFO, logger="screamingface_engine.process_memory")

    await _path(_Hook()).aggregate_result_async(RAW, **_kwargs(_selected(1, 2)))

    points = [
        record.getMessage().split()[2]
        for record in caplog.records
        if record.getMessage().startswith("process memory point=")
    ]
    assert [
        point
        for point in points
        if point in {"point=aggregate_start", "point=aggregate_marked", "point=aggregate_finalized"}
    ] == ["point=aggregate_start", "point=aggregate_marked", "point=aggregate_finalized"]


@pytest.mark.asyncio
async def test_scoring_finish_result_logs_three_memory_points(caplog):
    caplog.set_level(logging.INFO, logger="screamingface_engine.process_memory")

    await _scoring().finish_result("[]")

    points = [
        record.getMessage().split()[2]
        for record in caplog.records
        if record.getMessage().startswith("process memory point=")
    ]
    assert [
        point
        for point in points
        if point in {"point=aggregate_start", "point=aggregate_marked", "point=aggregate_finalized"}
    ] == ["point=aggregate_start", "point=aggregate_marked", "point=aggregate_finalized"]
