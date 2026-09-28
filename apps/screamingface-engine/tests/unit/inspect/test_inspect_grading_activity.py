"""Actual imported scoring emits case activity in the extra-enabled CI lane."""

import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.grading_activity import grading_activity
from screamingface_engine.observations import RunObservations


@pytest.mark.asyncio
async def test_imported_scorer_emits_real_grading_outcome(monkeypatch):
    scorer = pytest.importorskip("inspect_ai.scorer")

    from screamingface_engine.benchmarks.spine.payloads import TextPayload
    from screamingface_engine.benchmarks.spine.scored import GradeRequest
    from screamingface_engine_inspect.shim import inspect_grade_case

    records = []
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.grading_activity.current_log_sink",
        lambda: lambda body, attrs, **kwargs: records.append(dict(attrs)),
    )
    run = RunObservations((ActivityObserver,))
    with run.bind():
        grading_activity(7, "completed")  # Answer recording precedes actual scoring.
        assert not records
        outcome = await inspect_grade_case(scorer.match(numeric=True))(
            GradeRequest(
                case_id=7,
                input=TextPayload(text="What is 6 times 7?"),
                answer=TextPayload(text="ANSWER: 42"),
                row={"case": {"status": "answered"}},
                material={"target": "42"},
            )
        )
    await run.aclose()
    assert outcome.score == 1.0
    assert [r["sf.activity.state"] for r in records] == ["started", "completed"]
    assert all(r["sf.activity.case_id"] == 7 for r in records)
