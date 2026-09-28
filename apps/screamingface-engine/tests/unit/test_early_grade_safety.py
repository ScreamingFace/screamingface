"""Direct request limits and terminal failures obey the shared progress contract."""

import json

import pytest
from test_ifeval_incremental_proof import _call
from test_spine_scored import _envelope, _grading, _Hook, _path, _selected

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.spine.incremental import Scoring
from screamingface_engine.benchmarks.spine.incremental_routes import case_result_endpoint
from screamingface_engine.observations import RunObservations
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["0:1000000000", "0:3", "0:0", "-1:2", "2:2"])
async def test_invalid_selection_never_reaches_loader(intent):
    loads = []

    def load(count):
        loads.append(count)
        pytest.fail("invalid selection reached asset loader")

    node = Url4Node("test")
    node.endpoint("/grade")(case_result_endpoint(load, available_case_count=2))
    with pytest.raises(ResolutionError):
        await _call(node, "/grade", "{}", intent)
    assert loads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("with_grade", [True, False])
async def test_aggregation_failures_publish_once_without_inventing_score(monkeypatch, with_grade):
    logs = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink",
        lambda: lambda body, attrs: logs.append(dict(attrs)),
    )
    # INVARIANT: terminal failures must advance coverage even within the coalescing window.
    monkeypatch.setattr("screamingface_engine.activity.progress.time.monotonic", lambda: 1.0)
    binding = Scoring(
        _path(_Hook()),
        "board",
        "v1",
        _selected(1, 2),
        lambda _: (5, -3),
        lambda cases: CandidateScore(score=0.5, metrics={}),
    )
    failure = {"error": {"code": "rate_limited", "message": "unavailable"}}
    with RunObservations((ActivityObserver,)).bind():
        first = (
            await binding.grade_row(json.dumps(_envelope(1, _grading(1))), 0)
            if with_grade
            else failure
        )
        raw = json.dumps([first, failure])
        result = await binding.finish(raw)
        await binding.finish(raw)
    assert [log["sf.progress.completed"] for log in logs] == [1, 2]
    assert [log["sf.progress.graded"] for log in logs] == ([1, 1] if with_grade else [0, 0])
    assert [log["sf.progress.score"] for log in logs] == (
        [0.5, 0.5] if with_grade else [None, None]
    )
    assert [case["status"] for case in result["cases"]] == (
        ["scored", "failed"] if with_grade else ["failed", "failed"]
    )


@pytest.mark.asyncio
async def test_selection_at_available_count_is_accepted():
    loads = []

    def load(count):
        loads.append(count)
        return Scoring(
            _path(_Hook()),
            "board",
            "v1",
            _selected(1, 2),
            lambda _: (5, -3),
            lambda cases: CandidateScore(score=0.5, metrics={}),
        )

    node = Url4Node("test")
    node.endpoint("/grade")(case_result_endpoint(load, available_case_count=2))
    result = json.loads(await _call(node, "/grade", json.dumps(_envelope(2, _grading(2))), "1:2"))
    assert loads == [2]
    assert result["result"]["case_id"] == 2
