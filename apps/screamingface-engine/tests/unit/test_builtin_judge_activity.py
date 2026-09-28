"""Audit real model-call observations through every built-in benchmark recipe."""

import json

import pytest
from activity_recipe_helpers import _run
from test_benchmark_stage_parity import assets

from screamingface_engine.benchmarks.builtins import BUILTIN_REGISTRATIONS


@pytest.mark.asyncio
@pytest.mark.parametrize("registration", BUILTIN_REGISTRATIONS, ids=lambda r: r.benchmark.id)
@pytest.mark.parametrize("fusion", [False, True], ids=["solo", "fusion"])
async def test_builtin_calls_keep_case_identity_and_terminal_outcome(
    tmp_path, monkeypatch, registration, fusion
):
    assets(registration, tmp_path, monkeypatch)
    result, events = await _run(registration, tmp_path, fusion)
    assert result["score"] is not None, json.dumps(result)
    calls = [e for e in events if e.get("sf.activity.kind") == "model_call"]
    assert calls
    missing = [e.get("sf.activity.model_id") for e in calls if "sf.activity.case_id" not in e]
    assert not missing, missing
    expected_case = str(result["cases"][0]["case_id"])
    assert all(str(e["sf.activity.case_id"]) == expected_case for e in calls)
    judges = [e for e in calls if e["sf.activity.model_id"] not in {"writer", "synth"}]
    assert all(e.get("sf.activity.role") == "judge" for e in judges)
    started = {e["sf.activity.id"] for e in calls if e["sf.activity.state"] == "started"}
    ended = {e["sf.activity.id"] for e in calls if e["sf.activity.state"] == "completed"}
    assert started == ended
