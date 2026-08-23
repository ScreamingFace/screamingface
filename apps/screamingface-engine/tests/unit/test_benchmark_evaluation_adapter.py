"""Deep-interface contracts for Benchmark-owned Evaluation semantics (OME-932)."""

from __future__ import annotations

import inspect
import json
from collections.abc import Sequence
from pathlib import Path

from screamingface_engine.benchmarks import Benchmark, BenchmarkRegistry, run_logs
from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    scored_case_result,
)
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.contract import CaseResult, encode_candidate_invocation
from screamingface_engine.benchmarks.definition import (
    BenchmarkEvaluation,
    BoundEvaluation,
    IndexedCaseResult,
)
from screamingface_engine.benchmarks.progress import discover_evaluation_progress
from url4 import RelExpr, render, text
from url4.peer.server import Request


def _case_result(case_id: int, score: float) -> CaseResult:
    return scored_case_result(
        selected_case=SelectedCase(case_id=case_id, input=f"question {case_id}", metadata={}),
        output=f"answer {case_id}",
        finish_reason="stop",
        grade={"method": "test", "score": score, "metrics": {}, "checks": []},
    )


def _case_envelope(case_id: int) -> str:
    from screamingface_engine.benchmarks import case_execution

    return case_execution._case_execution(
        Request(
            path=case_execution.CASE_EXECUTION_ROUTE,
            context=json.dumps(
                {
                    "case_id": case_id,
                    "candidate_invocation": encode_candidate_invocation(
                        f"answer {case_id}", "stop", None
                    ),
                    "grading": [{"verdict": "PASS"}],
                }
            ),
            intent="preserve",
            params={},
        )
    )


def test_one_evaluation_adapter_binds_once_and_owns_projection_and_scoring(
    tmp_path: Path,
) -> None:
    bindings: list[tuple[Path, int]] = []

    def bind(root: Path, selected_case_count: int) -> BoundEvaluation:
        bindings.append((root, selected_case_count))

        def grade(raw: str) -> IndexedCaseResult:
            case_id = int(json.loads(raw)["case_id"])
            return IndexedCaseResult(selected_index=case_id - 1, result=_case_result(case_id, 0.5))

        def score(cases: Sequence[CaseResult]) -> CandidateScore:
            values: list[float] = []
            for case in cases:
                assert case.grade is not None and case.grade.score is not None
                values.append(float(case.grade.score))
            return CandidateScore(score=sum(values) / len(values), metrics={})

        return BoundEvaluation(grade_case=grade, score_cases=score)

    evaluation = BenchmarkEvaluation(
        aggregate_route="/benchmarks/alpha/v1/aggregate",
        bind=bind,
    )
    benchmark = Benchmark(
        id="alpha",
        title="Alpha",
        description="Adapter fixture.",
        revision="v1",
        case_count=2,
        build=lambda _selected: text("unused"),
        evaluation=evaluation,
    )
    rendered = render(
        RelExpr(
            path=evaluation.aggregate_route,
            context="[]",
            intent=text("aggregate:2"),
        )
    )

    tracker = discover_evaluation_progress(
        BenchmarkRegistry((benchmark,)),
        rendered,
        assets_root=tmp_path,
    )
    assert tracker is not None
    first = tracker.record_case_execution(_case_envelope(1))
    second = tracker.record_case_execution(_case_envelope(2))

    assert bindings == [(tmp_path, 2)]
    assert first is not None and first.provisional_score == 0.5
    assert second is not None and second.provisional_score == 0.5


def test_unreleased_loose_progress_interfaces_are_replaced() -> None:
    assert "aggregate_route" not in inspect.signature(Benchmark).parameters
    assert not hasattr(run_logs, "register_case_projection")


def test_every_builtin_declares_one_private_evaluation_adapter() -> None:
    for benchmark in BUILTIN_BENCHMARKS:
        assert benchmark.evaluation is not None
        assert "evaluation" not in benchmark.resource(1)


def test_concrete_runtime_handlers_do_not_register_progress_projectors() -> None:
    root = Path(__file__).parents[2] / "src" / "screamingface_engine" / "benchmarks"
    offenders = [
        path.relative_to(root)
        for path in root.rglob("runtime.py")
        if "register_case_projection" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
