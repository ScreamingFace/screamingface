"""Offline full-value Case fixtures for durable recovery tests."""

from datetime import UTC, datetime

from test_report_panel import candidate

from screamingface import (
    BenchmarkInfo,
    CandidateResult,
    CaseGrade,
    CaseResult,
    OperationInfo,
    Report,
    Usage,
)


def large_report(count=4182):
    cases = tuple(
        CaseResult(
            case_id=index,
            input="contract " * 1250,
            output=f"answer {index}",
            finish_reason="stop",
            failures=[],
            grade=CaseGrade(method="deterministic", score=1.0, metrics={}, checks=[]),
            metadata={"category": f"clause {index % 41}"},
        )
        for index in range(count)
    )
    benchmark = BenchmarkInfo("contracteval", "fixture", count)
    item = CandidateResult(
        benchmark=benchmark,
        run_id="demo",
        name="model",
        started_at=datetime(2026, 9, 30, tzinfo=UTC),
        completed_at=datetime(2026, 9, 30, tzinfo=UTC),
        kind="model",
        url4=candidate("model", 1.0).url4,
        models=["demo"],
        score=1.0,
        coverage=1.0,
        metrics={},
        operations=[OperationInfo(id="op", kind="model", label="answer", depends_on=())],
        cases=cases,
        members=[],
        failures=[],
        usage=Usage(),
    )
    return Report(benchmark=item.benchmark, case_count=count, candidates=[item])
