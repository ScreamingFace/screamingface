"""Deep-interface contracts for Benchmark-owned Evaluation semantics (OME-932)."""

from __future__ import annotations

import inspect
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from screamingface_engine.benchmarks import Benchmark, BenchmarkRegistry, run_logs
from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    scored_case_result,
)
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.case_execution_contract import (
    CaseExecutionObservation,
    case_execution_outcome,
)
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


def _case_envelope(case_id: int) -> CaseExecutionObservation:
    from screamingface_engine.benchmarks import case_execution

    raw = case_execution._case_execution(
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
    return CaseExecutionObservation(raw=raw, outcome=case_execution_outcome(raw))


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


def test_ifeval_binding_does_not_load_the_full_instruction_corpus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from screamingface_engine.benchmarks.ifeval import aggregate as scoring
    from screamingface_engine.benchmarks.ifeval.definition import IFEVAL

    monkeypatch.setattr(scoring, "load_case_order", lambda _root: [1, 2])

    def reject_full_load(_directory: Path) -> dict[int, dict[str, object]]:
        raise AssertionError("full instruction corpus loaded")

    monkeypatch.setattr(scoring, "load_specs", reject_full_load)
    assert IFEVAL.evaluation is not None

    bound = IFEVAL.evaluation.bind(tmp_path, 1)

    assert isinstance(bound, BoundEvaluation)


def test_draco_binding_does_not_repeat_full_protocol_asset_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from screamingface_engine.benchmarks.draco import assets as protocol_assets
    from screamingface_engine.benchmarks.draco.definition import ASSET_BUNDLE_ID, DRACO

    root = tmp_path / ASSET_BUNDLE_ID
    root.mkdir()
    (root / "cases.json").write_text('[{"id":1,"input":"question"}]', encoding="utf-8")

    def reject_validation(
        _root: Path, _cases: list[dict[str, object]]
    ) -> dict[int, dict[str, object]]:
        raise AssertionError("full protocol validation repeated")

    monkeypatch.setattr(protocol_assets, "validate_protocol_assets", reject_validation)
    assert DRACO.evaluation is not None

    bound = DRACO.evaluation.bind(tmp_path, 1)

    assert isinstance(bound, BoundEvaluation)


def test_healthbench_binding_loads_rubric_points_only_when_a_case_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from screamingface_engine.benchmarks.healthbench import aggregate as scoring
    from screamingface_engine.benchmarks.healthbench.definition import (
        HEALTHBENCH_WORST30,
        WORST30_EXAM,
    )
    from screamingface_engine.benchmarks.healthbench.exam import ASSET_BUNDLE_ID

    root = tmp_path / ASSET_BUNDLE_ID
    root.mkdir()
    case_id = WORST30_EXAM.case_ids[0]
    (root / "cases.json").write_text(
        json.dumps([{"id": case_id, "input": "question"}]), encoding="utf-8"
    )

    def reject_rubric_load(_root: Path, _case_id: int) -> list[int] | None:
        raise AssertionError("rubric loaded during bind")

    monkeypatch.setattr(scoring, "load_rubric_points", reject_rubric_load)
    assert HEALTHBENCH_WORST30.evaluation is not None

    bound = HEALTHBENCH_WORST30.evaluation.bind(tmp_path, 1)

    assert isinstance(bound, BoundEvaluation)
