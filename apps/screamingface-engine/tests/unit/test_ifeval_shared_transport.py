"""IFEval retains its canonical semantics through the shared transport."""

import json

import pytest
from test_ifeval_aggregate import _SPECS, _evaluation

from screamingface_engine.benchmarks.ifeval import grade
from screamingface_engine.benchmarks.ifeval.scoring import scoring


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_shared_binding_matches_batch_without_regrading(tmp_path, monkeypatch, failed):
    (tmp_path / "instructions").mkdir()
    for key, spec in _SPECS.items():
        (tmp_path / "instructions" / f"{key}.json").write_text(json.dumps(spec))
    # INVARIANT: installed order determines position, never sorted case IDs.
    order = [2, 1]
    (tmp_path / "cases.json").write_text(json.dumps([{"id": i} for i in order]))
    first = _evaluation(2, [True], [True])
    second = (
        {"error": {"message": "unavailable", "code": "provider_error"}}
        if failed
        else _evaluation(1, [True, False], [True, True])
    )
    expected = grade.aggregate(
        json.dumps([first, second]), _SPECS, "ifeval", order, selected_case_count=2
    )
    original = grade._grade_case
    calls = []

    async def count(request):
        calls.append(request.case_id)
        return await original(request)

    monkeypatch.setattr(grade, "_grade_case", count)
    binding = scoring(tmp_path, 2)
    rows: list[object] = [await binding.grade_row(json.dumps(first), 0)]
    rows.append(second if failed else await binding.grade_row(json.dumps(second), 1))
    assert await binding.finish(json.dumps(rows)) == expected
    assert calls == ([2] if failed else [2, 1])


@pytest.mark.asyncio
async def test_public_case_result_uses_canonical_ifeval_grader():
    path = grade.aggregation(_SPECS)
    selected = grade.selected_cases(_SPECS, [2, 1], 2)[0]
    indexed = path.reader.index(json.dumps([_evaluation(2, [True], [True])]), (2,))
    result = await path.case_result(selected, 0, indexed, _SPECS.get, None)
    assert result is not None and result.case_id == 2
    assert result.grade is not None and result.grade.score == 1.0
