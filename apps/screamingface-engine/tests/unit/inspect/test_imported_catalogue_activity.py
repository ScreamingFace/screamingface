"""Every shipped deterministic Inspect board executes through the real connector."""

import json

import pytest

pytest.importorskip("inspect_ai")

from activity_recipe_helpers import _run  # noqa: E402

from screamingface_engine_inspect.boards import BOARDS, imported_board  # noqa: E402


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [b.key for b in BOARDS if b.judge is None])
@pytest.mark.parametrize("fusion", [False, True], ids=["solo", "fusion"])
async def test_imported_catalogue_case_activity(tmp_path, key, fusion):
    board = imported_board(key)
    root = tmp_path / board.benchmark.id
    (root / "targets").mkdir(parents=True)
    (root / "cases.json").write_text(json.dumps([{"id": 1, "input": "Choose the answer."}]))
    (root / "targets" / "1.json").write_text(
        json.dumps(
            {
                "target": "E",
                "choices": ["a", "b", "c", "d", "Tea is a warm drink"],
            }
        )
    )
    result, events = await _run(board.registration, tmp_path, fusion)
    assert result["score"] is not None, result
    calls = [e for e in events if e.get("sf.activity.kind") == "model_call"]
    assert len([e for e in calls if e["sf.activity.state"] == "completed"]) == (3 if fusion else 1)
    assert all(str(e.get("sf.activity.case_id")) == "1" for e in calls)
    grading = [e for e in events if e["sf.activity.kind"] == "grading"]
    assert [e["sf.activity.state"] for e in grading] == ["started", "completed"]
    assert all(e.get("sf.activity.case_id") == 1 for e in grading)
    assert events[-1]["sf.activity.kind"] == "aggregation"
    assert events[-1]["sf.activity.state"] == "completed"
