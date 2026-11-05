from __future__ import annotations

from datetime import UTC, datetime

import pytest

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import _compiled_operation


def _cases() -> tuple[sf.CaseResult, ...]:
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


def test_pipeline_result_preserves_its_kind_and_serial_operation_dependencies() -> None:
    benchmark = sf.BenchmarkInfo(
        id="ifeval",
        revision="fixture-revision",
        case_count=1,
    )
    compiled = compile_candidate(
        sf.Pipeline([sf.Model("provider/draft"), sf.Model("provider/review")])
    )
    assert compiled.url4 is not None
    result = sf.CandidateResult(
        benchmark=benchmark,
        run_id="run_pipeline",
        started_at=datetime(2026, 8, 12, tzinfo=UTC),
        completed_at=datetime(2026, 8, 12, 0, 0, 1, tzinfo=UTC),
        name="draft->review",
        kind="pipeline",
        url4=compiled.url4,
        models=("provider/draft", "provider/review"),
        operations=(
            _compiled_operation(
                id="op_model_1",
                kind="model",
                label="draft answer",
                depends_on=(),
            ),
            _compiled_operation(
                id="op_model_2",
                kind="model",
                label="review answer",
                depends_on=("op_model_1",),
            ),
        ),
        score=1.0,
        coverage=1.0,
        metrics={},
        cases=_cases(),
        members=(),
        failures=(),
        usage=sf.Usage(),
    )

    assert result.kind == "pipeline"
    assert result.members == ()
    assert result.to_dict()["kind"] == "pipeline"


def test_pipeline_result_cannot_claim_direct_fusion_members() -> None:
    benchmark = sf.BenchmarkInfo(
        id="ifeval",
        revision="fixture-revision",
        case_count=1,
    )
    member = sf.MemberResult(
        operation_id="op_model_1",
        name="draft",
        kind="model",
        models=("provider/draft",),
        failures=None,
        duration_ms=None,
        usage=None,
    )

    with pytest.raises(
        ValueError,
        match="Pipeline Candidate cannot contain direct fanout members",
    ):
        sf.CandidateResult(
            benchmark=benchmark,
            run_id="run_pipeline",
            started_at=datetime(2026, 8, 12, tzinfo=UTC),
            completed_at=datetime(2026, 8, 12, 0, 0, 1, tzinfo=UTC),
            name="draft->review",
            kind="pipeline",
            url4="(model_1:0.0:/provider/draft!'draft')!'$model_1'",
            models=("provider/draft", "provider/review"),
            operations=(
                _compiled_operation(
                    id="op_model_1",
                    kind="model",
                    label="draft answer",
                    depends_on=(),
                ),
            ),
            score=1.0,
            coverage=1.0,
            metrics={},
            cases=_cases(),
            members=(member,),
            failures=(),
            usage=sf.Usage(),
        )
