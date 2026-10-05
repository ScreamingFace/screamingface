"""Offline ContractEval-sized Report for trying notebook pagination (no model calls)."""

from datetime import UTC, datetime

import screamingface as sf
from screamingface.operation import OperationInfo


def demo_report(count: int = 4182) -> sf.Report:
    """Synthetic data only; these scores are illustrative, not benchmark findings."""
    benchmark = sf.BenchmarkInfo("contracteval-demo", "synthetic", count)
    start = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    cases = [_case(index) for index in range(count)]
    scored = [case for case in cases if case.grade is not None]
    result = sf.CandidateResult(
        benchmark=benchmark,
        run_id="synthetic-contracteval",
        name="Demo candidate",
        kind="model",
        url4="(@)!'review'",
        models=["demo/model"],
        operations=[OperationInfo(id="answer", kind="model", label="Answer", depends_on=())],
        started_at=start,
        completed_at=start,
        score=0.75,
        coverage=round(len(scored) / count, 4),
        metrics={"pass_rate": 0.75},
        cases=cases,
        members=[],
        failures=[],
        usage=sf.Usage(),
    )
    return sf.Report(benchmark=benchmark, case_count=count, candidates=[result])


def _case(index: int) -> sf.CaseResult:
    failed = index % 19 == 0
    text = f"Synthetic contract {index}. The parties agree to the following provisions.\n" * 200
    return sf.CaseResult(
        case_id=index + 1,
        input=text + "\nFind the relevant clause.",
        output=None if failed else f"Clause {index % 41}: This agreement terminates on notice.",
        finish_reason=None if failed else "stop",
        grade=None
        if failed
        else sf.CaseGrade(
            method="deterministic", score=0.0 if index % 4 == 0 else 1.0, metrics={}, checks=[]
        ),
        failures=[
            sf.Failure(
                stage="grading",
                code="grading_failed",
                message="Synthetic timeout",
                case_id=index + 1,
            )
        ]
        if failed
        else [],
        metadata={"category": f"Clause category {index % 41 + 1:02d}", "synthetic": True},
    )
