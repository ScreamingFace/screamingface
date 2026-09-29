"""Early grade transport preserves final request accounting under retries and collisions."""

import json

import pytest
from test_grading_accounting import _accounting
from test_spine_scored import _envelope, _grading, _Hook, _path, _selected

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.contract import CandidateResult
from screamingface_engine.benchmarks.spine.incremental import Scoring
from screamingface_engine.benchmarks.spine.scored import CaseGradeOutcome
from screamingface_engine.grading_accounting import (
    GradingEvidenceOwner,
    accounting_for_grading_evidence,
    capture_grading_requests,
    reconcile_candidate_grading_accounting,
    register_grading_request,
)
from screamingface_engine.observations import RunObservations
from screamingface_engine.operation_accounting import OperationCache
from screamingface_engine.operation_calls import (
    capture_request_accounting,
    operation_call_identity,
    record_operation_call,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["retry", "hit", "shared-key"])
async def test_batch_and_early_final_accounting_match_with_progress(mode, monkeypatch):
    monkeypatch.setattr(
        "screamingface_engine.benchmarks.progress.current_log_sink", lambda: lambda *_: None
    )
    old, old_calls = await _evaluate(mode, early=False)
    new, new_calls = await _evaluate(mode, early=True)
    assert new == old
    assert new_calls == old_calls == (4 if mode == "retry" else 2)
    evidence = [case.grade.checks[0].evidence[0] for case in new.cases if case.grade is not None]
    if mode == "shared-key":
        assert all(e.accounting is None for e in evidence)
    else:
        for item in evidence:
            assert item.accounting is not None
            assert item.accounting.usage.cost_usd == ("0.2" if mode == "retry" else "0")
            assert item.accounting.cache.hits == (1 if mode == "hit" else 0)


async def _evaluate(mode, *, early):
    async def grade(request):
        owner = GradingEvidenceOwner(
            benchmark_id="board", case_id=request.case_id, check_id="check", sequence=1
        )
        context = "shared" if mode == "shared-key" else str(request.case_id)
        register_grading_request(owner, path="/judge", params={}, context=context, intent="")
        receipt = _accounting("0.1")
        if mode == "hit":
            receipt = receipt.model_copy(
                update={
                    "usage": receipt.usage.model_copy(update={"cost_usd": "0"}),
                    "cache": OperationCache(hits=1, misses=0, bypasses=0, unknown=0),
                    "provider_attempts": 0,
                }
            )
        for _ in range(2 if mode == "retry" else 1):
            with operation_call_identity("/judge", {}, context=context, intent=""):
                record_operation_call("verdict", "stop", receipt)
        accounting = accounting_for_grading_evidence(owner)
        return CaseGradeOutcome(
            score=1.0,
            metrics={},
            checks=[
                {
                    "type": "rubric",
                    "id": "check",
                    "label": "Check",
                    "outcome": "MET",
                    "score": 1.0,
                    "metadata": {},
                    "evidence": [
                        {
                            "sequence": 1,
                            "producer": {"type": "model", "id": "judge"},
                            "valid": True,
                            "outcome": "MET",
                            "raw_output": "verdict",
                            "metadata": {},
                            "accounting": None if accounting is None else accounting.model_dump(),
                        }
                    ],
                }
            ],
        )

    scoring = Scoring(
        _path(_Hook(), grade_case=grade),
        "board",
        "v1",
        _selected(1, 2),
        lambda _: (5, -3),
        lambda cases: CandidateScore(score=1.0, metrics={}),
    )
    rows = [_envelope(n, _grading(n)) for n in (1, 2)]
    run = RunObservations((ActivityObserver,))
    try:
        with run.bind(), capture_request_accounting() as calls, capture_grading_requests():
            if early:
                completed = [
                    await scoring.grade_row(json.dumps(row), index)
                    for index, row in enumerate(rows)
                ]
                payload = await scoring.finish(json.dumps(completed))
            else:
                payload = await scoring.path.aggregate_async(
                    json.dumps(rows),
                    benchmark_id="board",
                    benchmark_revision="v1",
                    selected_cases=scoring.selected,
                    grading_material=scoring.material,
                    scorer=scoring.scorer,
                )
            result = CandidateResult.model_validate(payload)
            reconcile_candidate_grading_accounting(result)
            return result, len(calls)
    finally:
        await run.aclose()
