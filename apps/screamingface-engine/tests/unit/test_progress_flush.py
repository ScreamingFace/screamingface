"""Fast batches publish their tail, including when final reduction fails."""

import json

import pytest
from test_spine_scored import _envelope, _grading, _Hook, _path, _selected

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.observations import RunObservations


@pytest.mark.asyncio
@pytest.mark.parametrize("final_failure", [False, True])
async def test_fast_batch_flushes_tail_before_observation_closes(monkeypatch, final_failure):
    snapshots = []
    monkeypatch.setattr("screamingface_engine.activity.progress.time.monotonic", lambda: 1.0)
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink",
        lambda: lambda body, attrs: snapshots.append(dict(attrs)),
    )
    calls = 0

    def scorer(cases):
        nonlocal calls
        calls += 1
        if final_failure and calls == 2:
            raise RuntimeError("final reduction failed")
        return CandidateScore(score=0.5, metrics={})

    run = RunObservations((ActivityObserver,))
    try:
        with run.bind():
            task = _path(_Hook()).aggregate_async(
                json.dumps([_envelope(1, _grading(1)), _envelope(2, _grading(2))]),
                benchmark_id="board",
                benchmark_revision="v1",
                selected_cases=_selected(1, 2),
                grading_material=lambda _: (5, -3),
                scorer=scorer,
            )
            if final_failure:
                with pytest.raises(RuntimeError, match="final reduction failed"):
                    await task
            else:
                await task
            assert [s["sf.progress.completed"] for s in snapshots] == [1, 2]
    finally:
        await run.aclose()


@pytest.mark.asyncio
async def test_early_grade_transport_flushes_without_regrading(monkeypatch):
    from screamingface_engine.benchmarks.spine.incremental import Scoring

    snapshots = []
    monkeypatch.setattr("screamingface_engine.activity.progress.time.monotonic", lambda: 1.0)
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink",
        lambda: lambda body, attrs: snapshots.append(dict(attrs)),
    )
    hook = _Hook()
    scoring = Scoring(
        _path(hook),
        "board",
        "v1",
        _selected(1, 2),
        lambda _: (5, -3),
        lambda cases: CandidateScore(score=0.5, metrics={}),
    )
    run = RunObservations((ActivityObserver,))
    try:
        with run.bind():
            rows = [
                await scoring.grade_row(json.dumps(_envelope(n, _grading(n))), n - 1)
                for n in (1, 2)
            ]
            assert [s["sf.progress.completed"] for s in snapshots] == [1]
            await scoring.finish(json.dumps(rows))
            await scoring.finish(json.dumps(rows))
            assert [s["sf.progress.completed"] for s in snapshots] == [1, 2]
            assert [r.case_id for r in hook.requests] == [1, 2]
    finally:
        await run.aclose()
