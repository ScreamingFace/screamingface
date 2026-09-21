from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

import screamingface as sf
from screamingface._evaluation.model import _compiled_operation

NOW = datetime(2026, 7, 25, 16, 0, tzinfo=UTC)


def operations(*ids: str) -> tuple[sf.OperationInfo, ...]:
    return tuple(
        _compiled_operation(
            id=operation_id,
            kind="model",
            label=operation_id,
            depends_on=(),
        )
        for operation_id in ids
    )


MODEL_OPERATIONS = operations("op_model")
FUSION_OPERATIONS = operations("op_first", "op_second")


def case_results() -> tuple[sf.CaseResult, ...]:
    return (
        sf.CaseResult(
            case_id=1,
            input="Question",
            output="Answer",
            finish_reason="stop",
            grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
            failures=(),
            metadata={},
        ),
    )


def member(name: str = "member") -> sf.MemberResult:
    return sf.MemberResult(
        operation_id=f"op_{name}",
        name=name,
        kind="model",
        models=("provider/model",),
        failures=(),
        duration_ms=10,
        usage=sf.Usage(input_tokens=1),
    )


def candidate(
    name: str = "candidate",
    *,
    score: float | None = 0.5,
) -> sf.CandidateResult:
    return sf.CandidateResult(
        benchmark=benchmark(),
        run_id=f"run-{name}",
        started_at=NOW,
        completed_at=NOW + timedelta(milliseconds=20),
        name=name,
        kind="fusion",
        url4="(@)!'candidate'",
        models=("provider/model",),
        operations=FUSION_OPERATIONS,
        score=score,
        coverage=1.0 if score is not None else 0.0,
        metrics={} if score is None else {"score": score},
        cases=case_results(),
        members=(member("first"), member("second")),
        failures=(),
        usage=sf.Usage(input_tokens=1),
    )


def benchmark() -> sf.BenchmarkInfo:
    return sf.BenchmarkInfo(
        id="bench-1",
        revision="fixture-revision",
        case_count=10,
    )


def test_report_values_cover_members_and_collections() -> None:
    selected = candidate()
    value = sf.Report(
        benchmark=benchmark(),
        case_count=1,
        candidates=(selected,),
    )

    assert member().to_dict()["name"] == "member"
    assert value.candidates[:] == (selected,)
    with pytest.raises(KeyError, match="unknown Candidate"):
        _ = value.candidates["missing"]


def test_candidate_metrics_preserve_json_compatible_values() -> None:
    result = sf.CandidateResult(
        benchmark=benchmark(),
        run_id="run-candidate",
        started_at=NOW,
        completed_at=NOW + timedelta(milliseconds=20),
        name="candidate",
        kind="fusion",
        url4="(@)!'candidate'",
        models=("provider/model",),
        operations=FUSION_OPERATIONS,
        score=0.5,
        coverage=1.0,
        metrics={"score": None, "axis_scores": {"correctness": 0.5}},
        cases=case_results(),
        members=(member("first"), member("second")),
        failures=(),
        usage=sf.Usage(input_tokens=1),
    )

    assert result.to_dict()["metrics"] == {
        "score": None,
        "axis_scores": {"correctness": 0.5},
    }


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: sf.Failure(
                stage="candidate",
                code="candidate_failed",
                message="x",
                retryable=cast(Any, 1),
                operation_id="op_1",
            ),
            "boolean",
        ),
        (
            lambda: sf.Failure(
                stage=cast(Any, "planning"),
                code="candidate_failed",
                message="x",
                retryable=False,
                operation_id="op_1",
            ),
            "candidate.*grading.*aggregation",
        ),
        (
            lambda: sf.Failure(
                stage="candidate",
                code="candidate_failed",
                message="x",
                retryable=False,
                operation_id=" ",
            ),
            "operation_id",
        ),
        (
            lambda: sf.CandidateResult(
                benchmark=benchmark(),
                run_id="run",
                started_at=NOW,
                completed_at=NOW,
                name="x",
                kind="model",
                url4="(@)!'x'",
                models=("m",),
                operations=MODEL_OPERATIONS,
                score=None,
                coverage=0.0,
                metrics={"score": 0.0},
                cases=case_results(),
                members=(),
                failures=(),
                usage=sf.Usage(),
            ),
            "cannot contain metrics",
        ),
        (
            lambda: sf.CandidateResult(
                benchmark=benchmark(),
                run_id="run",
                started_at=NOW,
                completed_at=NOW,
                name="x",
                kind="model",
                url4="(@)!'x'",
                models=("m", "m"),
                operations=MODEL_OPERATIONS,
                score=0.5,
                coverage=1.0,
                metrics={"score": 0.5},
                cases=case_results(),
                members=(member(),),
                failures=(),
                usage=sf.Usage(),
            ),
            "unique",
        ),
        (
            lambda: sf.CandidateResult(
                benchmark=benchmark(),
                run_id="run",
                started_at=NOW,
                completed_at=NOW,
                name="x",
                kind="model",
                url4="(@)!'x'",
                models=("m",),
                operations=MODEL_OPERATIONS,
                score=0.5,
                coverage=1.0,
                metrics={"score": 0.5},
                cases=case_results(),
                members=(member(),),
                failures=(),
                usage=sf.Usage(),
            ),
            "cannot contain members",
        ),
        (
            lambda: sf.CandidateResult(
                benchmark=benchmark(),
                run_id="run",
                started_at=NOW,
                completed_at=NOW,
                name="x",
                kind="fusion",
                url4="(@)!'x'",
                models=("m",),
                operations=MODEL_OPERATIONS,
                score=0.5,
                coverage=1.0,
                metrics={"score": 0.5},
                cases=case_results(),
                members=(),
                failures=(),
                usage=sf.Usage(),
            ),
            "at least one direct member",
        ),
        (
            lambda: sf.CandidateResult(
                benchmark=benchmark(),
                run_id="run",
                started_at=NOW,
                completed_at=NOW,
                name="x",
                kind="model",
                url4="(@)!'x'",
                models=("m",),
                operations=MODEL_OPERATIONS,
                score=0.5,
                coverage=1.0,
                metrics={"score": 0.5},
                cases=case_results(),
                members=(),
                failures=(
                    sf.Failure(
                        stage="candidate",
                        code="candidate_failed",
                        message="failed",
                        retryable=False,
                        operation_id="op_1",
                        case_id=1,
                    ),
                ),
                usage=sf.Usage(),
            ),
            "cannot claim a Case id",
        ),
        (
            lambda: sf.Report(benchmark=benchmark(), case_count=1, candidates=()),
            "at least one",
        ),
        (
            lambda: sf.Report(
                benchmark=benchmark(),
                case_count=1,
                candidates=cast(Any, ("bad",)),
            ),
            "CandidateResult",
        ),
        (
            lambda: sf.Usage(input_tokens=cast(Any, True)),
            "non-negative integer",
        ),
        (lambda: sf.Usage(output_tokens=-1), "non-negative integer"),
        (lambda: sf.Usage(cost_usd=cast(Any, 1.2)), "decimal string"),
        (
            lambda: sf.MemberResult(
                operation_id="op_x",
                name="x",
                kind=cast(Any, "bad"),
                models=("m",),
                failures=(),
                duration_ms=1,
                usage=sf.Usage(),
            ),
            "kind",
        ),
        (
            lambda: sf.MemberResult(
                operation_id="op_x",
                name="x",
                kind="model",
                models=(),
                failures=(),
                duration_ms=1,
                usage=sf.Usage(),
            ),
            "must not be empty",
        ),
        (
            lambda: sf.MemberResult(
                operation_id="op_x",
                name="x",
                kind="model",
                models=("m",),
                failures=cast(Any, ("bad",)),
                duration_ms=1,
                usage=sf.Usage(),
            ),
            "Failure",
        ),
        (
            lambda: sf.MemberResult(
                operation_id="op_x",
                name="x",
                kind="model",
                models=("m",),
                failures=(),
                duration_ms=-1,
                usage=sf.Usage(),
            ),
            "duration_ms",
        ),
        (
            lambda: sf.MemberResult(
                operation_id=" ",
                name="x",
                kind="model",
                models=("m",),
                failures=(),
                duration_ms=1,
                usage=sf.Usage(),
            ),
            "operation_id",
        ),
    ],
)
def test_report_values_reject_invalid_state(factory: Any, message: str) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        factory()


def test_candidate_rejects_invalid_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        sf.CandidateResult(
            benchmark=benchmark(),
            run_id="run",
            started_at=datetime(2026, 1, 1),
            completed_at=NOW,
            url4="(@)!'x'",
            name="x",
            kind="model",
            models=("m",),
            operations=MODEL_OPERATIONS,
            score=0.5,
            coverage=1.0,
            metrics={"score": 0.5},
            cases=case_results(),
            members=(),
            failures=(),
            usage=sf.Usage(),
        )
    with pytest.raises(ValueError, match="cannot precede"):
        sf.CandidateResult(
            benchmark=benchmark(),
            run_id="run",
            started_at=NOW,
            completed_at=NOW - timedelta(seconds=1),
            url4="(@)!'x'",
            name="x",
            kind="model",
            models=("m",),
            operations=MODEL_OPERATIONS,
            score=0.5,
            coverage=1.0,
            metrics={"score": 0.5},
            cases=case_results(),
            members=(),
            failures=(),
            usage=sf.Usage(),
        )


def test_fusion_member_operation_ids_must_be_unique() -> None:
    first = member("first")
    second = sf.MemberResult(
        operation_id=first.operation_id,
        name="second",
        kind="model",
        models=("provider/other",),
        failures=(),
        duration_ms=10,
        usage=sf.Usage(),
    )

    with pytest.raises(ValueError, match="operation IDs must be unique"):
        sf.CandidateResult(
            benchmark=benchmark(),
            run_id="run",
            started_at=NOW,
            completed_at=NOW,
            name="fusion",
            kind="fusion",
            url4="(@)!'x'",
            models=("provider/model", "provider/other"),
            operations=FUSION_OPERATIONS,
            score=0.5,
            coverage=1.0,
            metrics={"score": 0.5},
            cases=case_results(),
            members=(first, second),
            failures=(),
            usage=sf.Usage(),
        )


def test_candidate_result_rejects_unknown_operation_references() -> None:
    unknown_failure = sf.Failure(
        stage="candidate",
        code="candidate_failed",
        message="failed",
        retryable=False,
        operation_id="op_missing",
    )
    with pytest.raises(ValueError, match="unknown Operation ID 'op_missing'"):
        sf.CandidateResult(
            benchmark=benchmark(),
            run_id="run",
            started_at=NOW,
            completed_at=NOW,
            name="model",
            kind="model",
            url4="(@)!'x'",
            models=("provider/model",),
            operations=MODEL_OPERATIONS,
            score=1.0,
            coverage=1.0,
            metrics={},
            cases=case_results(),
            members=(),
            failures=(unknown_failure,),
            usage=sf.Usage(),
        )

    with pytest.raises(ValueError, match="unknown Operation ID 'op_missing'"):
        sf.CandidateResult(
            benchmark=benchmark(),
            run_id="run",
            started_at=NOW,
            completed_at=NOW,
            name="fusion",
            kind="fusion",
            url4="(@)!'x'",
            models=("provider/model",),
            operations=FUSION_OPERATIONS,
            score=0.5,
            coverage=1.0,
            metrics={"score": 0.5},
            cases=case_results(),
            members=(member("first"), member("missing")),
            failures=(),
            usage=sf.Usage(),
        )
