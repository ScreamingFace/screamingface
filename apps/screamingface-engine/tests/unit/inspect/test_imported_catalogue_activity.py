"""Every shipped deterministic Inspect benchmark executes through the real connector."""

import json

import pytest

pytest.importorskip("inspect_ai")

from activity_recipe_helpers import _run  # noqa: E402
from replayed_cases_helpers import STAND_IN_METADATA  # noqa: E402

from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [b.key for b in BENCHMARKS if b.judge is None])
@pytest.mark.parametrize("fusion", [False, True], ids=["solo", "fusion"])
async def test_imported_catalogue_case_activity(tmp_path, key, fusion):
    benchmark = imported_benchmark(key)
    root = tmp_path / benchmark.benchmark.id
    (root / "targets").mkdir(parents=True)
    (root / "cases.json").write_text(json.dumps([{"id": 1, "input": "Choose the answer."}]))
    material = {"target": "E", "choices": ["a", "b", "c", "d", "Tea is a warm drink"]}
    # OME-1527: a scorer that reads a metadata key fails loudly without it; give it the
    # realistic stand-in its real Cases carry.
    if key in STAND_IN_METADATA:
        material["metadata"] = STAND_IN_METADATA[key]
    (root / "targets" / "1.json").write_text(json.dumps(material))
    result, events = await _run(benchmark.registration, tmp_path, fusion)
    assert result["score"] is not None, result
    calls = [e for e in events if e.get("sf.activity.kind") == "model_call"]
    assert len([e for e in calls if e["sf.activity.state"] == "completed"]) == (3 if fusion else 1)
    assert all(str(e.get("sf.activity.case_id")) == "1" for e in calls)
    grading = [e for e in events if e["sf.activity.kind"] == "grading"]
    assert [e["sf.activity.state"] for e in grading] == ["started", "completed"]
    assert all(e.get("sf.activity.case_id") == 1 for e in grading)
    assert events[-1]["sf.activity.kind"] == "aggregation"
    assert events[-1]["sf.activity.state"] == "completed"
