"""Every built-in publishes canonical scores; async grading publishes before waiting."""

import asyncio
import json
from dataclasses import replace

import pytest
from test_shared_grading_aggregation import _envelope, _grading, _Hook, _path, _selected

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.observations import RunObservations


@pytest.mark.asyncio
async def test_shared_aggregate_publishes_before_second_async_grade(monkeypatch):
    waiting, release = asyncio.Event(), asyncio.Event()
    hook = _Hook()
    snapshots = []

    async def grade(request):
        if request.case_id == 2:
            waiting.set()
            await release.wait()
        return await hook(request)

    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink",
        lambda: lambda body, attrs: snapshots.append(dict(attrs)),
    )
    run = RunObservations((ActivityObserver,))
    with run.bind():
        task = asyncio.create_task(
            replace(_path(hook), grade_case=grade).aggregate_async(
                json.dumps([_envelope(1, _grading(1)), _envelope(2, _grading(2))]),
                benchmark_id="board",
                benchmark_revision="v1",
                selected_cases=_selected(1, 2),
                grading_material=lambda _: (5, -3),
                scorer=lambda cases: CandidateScore(score=0.5, metrics={}),
            )
        )
        try:
            await asyncio.wait_for(waiting.wait(), 5)
            assert not task.done()
            assert snapshots[0]["sf.progress.graded"] == 1
            assert snapshots[0]["sf.progress.score"] == 0.5
        finally:
            release.set()
            result = await asyncio.wait_for(task, 5)
            await run.aclose()
    assert result["score"] == 0.5
    assert [request.case_id for request in hook.requests] == [1, 2]
