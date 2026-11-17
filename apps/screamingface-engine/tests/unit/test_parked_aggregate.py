"""FEATURE memory fix 3 (OME-1835), unit 2: the parked aggregate face writes the held bytes.

INVARIANT defended: ``encode_result_body(await aggregate_body_async(...))`` equals
``compact_json((await aggregate_result_async(...)).as_payload())`` for the same inputs, with a
bound Case-result store and with none, serial and concurrent marking, and a filled Case. Live
progress gets the builder's scoring projection; a store failure is a CaseParkingError.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from test_shared_grading_aggregation import _envelope, _grading, _Hook, _path, _selected, mean_score

from screamingface_engine.benchmarks.case_result_store import (
    CaseResultStore,
    binding_case_results,
)
from screamingface_engine.benchmarks.contract import CandidateResult, CaseResult
from screamingface_engine.benchmarks.result_body import compact_json, encode_result_body
from screamingface_engine.benchmarks.result_builder import CaseParkingError
from screamingface_engine.benchmarks.scoring_projection import NOT_RETAINED, scoring_projection
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    BenchmarkAggregation,
)


def _kwargs(selected: Any) -> dict[str, Any]:
    return dict(
        benchmark_id="test-benchmark",
        benchmark_revision="rev",
        selected_cases=selected,
        grading_material=lambda case_id: (5, -3),
        scorer=mean_score,
    )


RAW = json.dumps([_envelope(1, _grading(1)), _envelope(2, _grading(2))])


def _face(concurrency: int) -> BenchmarkAggregation:
    return dataclasses.replace(_path(_Hook()), case_grading_concurrency=concurrency)


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", [True, False], ids=["store", "no-store"])
@pytest.mark.parametrize("concurrency", [1, 2])
@pytest.mark.parametrize("selection", [(1, 2), (1, 2, 3)], ids=["all-rows", "one-fill"])
async def test_the_parked_face_writes_the_held_bytes(
    tmp_path: Path, bound: bool, concurrency: int, selection: Sequence[int]
):
    held = await _face(concurrency).aggregate_result_async(RAW, **_kwargs(_selected(*selection)))
    store = CaseResultStore.create(tmp_path) if bound else None
    try:
        with binding_case_results(store):
            body = await _face(concurrency).aggregate_body_async(
                RAW, **_kwargs(_selected(*selection))
            )
            # WHY inside the block: a parked body reads its Cases from the open store.
            written = encode_result_body(body)
    finally:
        if store is not None:
            store.close()

    assert written == compact_json(held.as_payload())


@pytest.mark.asyncio
async def test_the_parked_face_logs_three_memory_points(caplog):
    caplog.set_level(logging.INFO, logger="screamingface_engine.process_memory")

    await _path(_Hook()).aggregate_body_async(RAW, **_kwargs(_selected(1, 2)))

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
async def test_progress_receives_the_builders_projection(monkeypatch: pytest.MonkeyPatch):
    published: list[CaseResult] = []

    def record(
        benchmark_id: str, benchmark_revision: str, result: CaseResult, *args: Any, **kwargs: Any
    ) -> None:
        published.append(result)

    monkeypatch.setattr(
        "screamingface_engine.benchmarks.shared_grading.benchmark_aggregation.completed_case",
        record,
    )

    await _path(_Hook()).aggregate_body_async(RAW, **_kwargs(_selected(1, 2, 3)))

    assert [result.case_id for result in published] == [1, 2, 3]
    assert all(result.input == NOT_RETAINED for result in published)
    assert all(scoring_projection(result) is result for result in published)


@pytest.mark.asyncio
async def test_a_bound_store_parks_one_row_per_case(tmp_path: Path):
    store = CaseResultStore.create(tmp_path)
    try:
        with binding_case_results(store):
            await _path(_Hook()).aggregate_body_async(RAW, **_kwargs(_selected(1, 2, 3)))
        assert len(store) == 3
    finally:
        store.close()


@pytest.mark.asyncio
async def test_a_closed_store_fails_with_case_parking_error(tmp_path: Path):
    store = CaseResultStore.create(tmp_path)
    store.close()

    with binding_case_results(store), pytest.raises(CaseParkingError) as raised:
        await _path(_Hook()).aggregate_body_async(RAW, **_kwargs(_selected(1, 2)))

    # WHY: the aggregate endpoints map OSError and ValueError to benchmark_unavailable.
    assert not isinstance(raised.value, (OSError, ValueError))


@pytest.mark.asyncio
async def test_the_held_face_is_unchanged():
    model = await _path(_Hook()).aggregate_result_async(RAW, **_kwargs(_selected(1, 2, 3)))

    assert isinstance(model, CandidateResult)
    assert model.as_payload() == await _path(_Hook()).aggregate_async(
        RAW, **_kwargs(_selected(1, 2, 3))
    )
