"""Canonical grading failures survive the early transport unchanged."""

import json

import pytest
from test_medxpert_aggregate import _graded_answer_route, _root, _rows

from screamingface_engine.benchmarks.medxpert.aggregate import scoring
from screamingface_engine.benchmarks.medxpert.definition import BENCHMARK_ID, REVISION


def _binding(tmp_path):
    return scoring(
        _root(tmp_path),
        benchmark_id=BENCHMARK_ID,
        benchmark_revision=REVISION,
        case_ids=(1,),
    )


def _failed():
    return _graded_answer_route(1, {"error": {"message": "checker failed", "kind": "ValueError"}})


@pytest.mark.asyncio
async def test_medxpert_failed_grade_round_trip_preserves_canonical_result(tmp_path):
    binding = _binding(tmp_path)
    raw = _failed()
    baseline = binding.aggregate(json.dumps([raw]))
    assert baseline["cases"][0]["failures"][0]["code"] == "medxpert_grading_failed"
    early = await binding.grade_row(json.dumps(raw), 0)
    assert await binding.finish(json.dumps([early])) == baseline


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [True, False])
async def test_medxpert_round_trip_rejects_conflicting_slice_metadata(tmp_path, failed):
    binding = _binding(tmp_path)
    raw = _failed() if failed else json.loads(_rows((1, "C")))[0]
    early = json.loads(await binding.grade_row(json.dumps(raw), 0))
    early["result"]["metadata"]["body_system"] = "wrong"
    with pytest.raises(ValueError):
        await binding.finish(json.dumps([early]))


@pytest.mark.asyncio
async def test_medxpert_scored_result_still_requires_slice_metadata(tmp_path):
    binding = _binding(tmp_path)
    early = json.loads(await binding.grade_row(json.dumps(json.loads(_rows((1, "C")))[0]), 0))
    early["result"]["metadata"].pop("body_system")
    with pytest.raises(ValueError):
        await binding.finish(json.dumps([early]))
