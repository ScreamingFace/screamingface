"""Exact, fail-open terminal progress discovery and accounting (OME-932)."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from screamingface_engine.benchmarks import (
    Benchmark,
    BenchmarkEvaluation,
    BenchmarkRegistry,
    BoundEvaluation,
    IndexedCaseResult,
    case_execution,
)
from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    failed_case_result,
    refused_case_result,
    scored_case_result,
)
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.case_execution_contract import (
    CaseExecutionObservation,
    case_execution_outcome,
)
from screamingface_engine.benchmarks.contract import CaseResult, encode_candidate_invocation
from screamingface_engine.benchmarks.progress import (
    EvaluationProgressTracker,
    discover_evaluation_progress,
)
from screamingface_engine.benchmarks.run_logs import (
    BenchmarkRunLogAdapter,
    record_candidate_failure,
)
from screamingface_engine.run_log_contract import LogScalar
from url4 import Node, RelExpr, RelUrl, expr, iterate, render, src, text
from url4.peer.server import Request

type CaseEvaluator = Callable[[str], IndexedCaseResult]
type CaseScorer = Callable[[Sequence[CaseResult]], CandidateScore]


def _projected_case(case_id: int, score: float) -> CaseResult:
    return scored_case_result(
        selected_case=SelectedCase(case_id=case_id, input=f"question {case_id}", metadata={}),
        output=f"answer {case_id}",
        finish_reason="stop",
        grade={"method": "test", "score": score, "metrics": {}, "checks": []},
    )


def _default_grade(raw: str) -> IndexedCaseResult:
    case_id = int(json.loads(raw)["case_id"])
    return IndexedCaseResult(case_id - 1, _projected_case(case_id, 1.0))


def _mean_score(cases: Sequence[CaseResult]) -> CandidateScore:
    scores: list[float] = []
    for case in cases:
        assert case.grade is not None and case.grade.score is not None
        scores.append(float(case.grade.score))
    return CandidateScore(score=sum(scores) / len(scores), metrics={})


def _benchmark(
    benchmark_id: str = "alpha",
    *,
    case_count: int = 100,
    aggregate_route: str = "/benchmarks/alpha/v1/aggregate",
    grade_case: CaseEvaluator = _default_grade,
    score_cases: CaseScorer = _mean_score,
) -> Benchmark:
    return Benchmark(
        id=benchmark_id,
        title="Progress benchmark",
        description="A terminal progress discovery fixture.",
        revision="progress-v1",
        case_count=case_count,
        build=lambda _selected: text("unused"),
        evaluation=BenchmarkEvaluation(
            aggregate_route=aggregate_route,
            bind=lambda _root, _selected: BoundEvaluation(grade_case, score_cases),
        ),
    )


def _aggregate_call(route: str, intent: Node) -> RelExpr:
    return RelExpr(path=route, context="[]", intent=intent)


def _route(benchmark: Benchmark) -> str:
    assert benchmark.evaluation is not None
    return benchmark.evaluation.aggregate_route


@pytest.mark.parametrize("selected", [1, 10, 100])
def test_exact_registered_aggregate_call_discovers_selected_total(selected: int) -> None:
    benchmark = _benchmark()
    rendered = render(_aggregate_call(_route(benchmark), text(f"aggregate:{selected}")))

    tracker = discover_evaluation_progress(
        BenchmarkRegistry((benchmark,)), rendered, assets_root=Path()
    )

    assert tracker is not None
    assert tracker.benchmark_id == benchmark.id
    assert tracker.total == selected


@pytest.mark.parametrize(
    "rendered",
    [
        "(((not-url4",
        render(_aggregate_call("/benchmarks/unknown/v1/aggregate", text("aggregate:10"))),
        render(_aggregate_call("/benchmarks/alpha/v1/aggregate", text("aggregate:0"))),
        render(_aggregate_call("/benchmarks/alpha/v1/aggregate", text("aggregate:01"))),
        render(_aggregate_call("/benchmarks/alpha/v1/aggregate", text("aggregate:101"))),
        render(_aggregate_call("/benchmarks/alpha/v1/aggregate", text("aggregate:ten"))),
        render(_aggregate_call("/benchmarks/alpha/v1/aggregate", RelUrl("/intent"))),
    ],
)
def test_missing_malformed_unknown_or_noncanonical_discovery_is_inert(rendered: str) -> None:
    assert (
        discover_evaluation_progress(
            BenchmarkRegistry((_benchmark(),)), rendered, assets_root=Path()
        )
        is None
    )


def test_multiple_registered_aggregate_calls_are_ambiguous_and_inert() -> None:
    benchmark = _benchmark()
    aggregate = _route(benchmark)
    rendered = render(
        expr(
            _aggregate_call(aggregate, text("aggregate:10")),
            _aggregate_call(aggregate, text("aggregate:10")),
            intent=text("$1"),
        )
    )

    assert (
        discover_evaluation_progress(BenchmarkRegistry((benchmark,)), rendered, assets_root=Path())
        is None
    )


def test_same_aggregate_route_declared_by_multiple_benchmarks_is_ambiguous_and_inert() -> None:
    alpha = _benchmark("alpha")
    beta = _benchmark("beta")
    rendered = render(_aggregate_call(_route(alpha), text("aggregate:1")))

    assert (
        discover_evaluation_progress(BenchmarkRegistry((alpha, beta)), rendered, assets_root=Path())
        is None
    )


def test_every_builtin_protocol_declares_and_discovers_its_exact_aggregate_route() -> None:
    for builtin in BUILTIN_BENCHMARKS:
        assert builtin.evaluation is not None
        fixture = _benchmark(
            builtin.id,
            case_count=builtin.case_count,
            aggregate_route=builtin.evaluation.aggregate_route,
        )
        tracker = discover_evaluation_progress(
            BenchmarkRegistry((fixture,)),
            render(builtin.protocol(1)),
            assets_root=Path(),
        )
        assert tracker is not None
        assert (tracker.benchmark_id, tracker.total) == (builtin.id, 1)


def test_registered_aggregate_inside_iteration_template_is_discovered() -> None:
    benchmark = _benchmark(case_count=1)
    rendered = render(
        iterate(
            [text("row")],
            body=(
                src(
                    _aggregate_call(_route(benchmark), text("aggregate:1")),
                    name="result",
                    weight=0.0,
                ),
            ),
            intent=text("$result"),
        )
    )

    tracker = discover_evaluation_progress(
        BenchmarkRegistry((benchmark,)), rendered, assets_root=Path()
    )

    assert tracker is not None
    assert (tracker.benchmark_id, tracker.total) == (benchmark.id, 1)


@pytest.mark.parametrize("template", ["intent", "reducer"])
def test_registered_aggregate_inside_iteration_tail_template_is_discovered(
    template: str,
) -> None:
    benchmark = _benchmark(case_count=1)
    aggregate = render(_aggregate_call(_route(benchmark), text("aggregate:1")))
    iteration = (
        iterate([text("row")], body=text("row"), intent=aggregate)
        if template == "intent"
        else iterate([text("row")], body=text("row"), intent=text("row"), reduce=aggregate)
    )

    tracker = discover_evaluation_progress(
        BenchmarkRegistry((benchmark,)), render(iteration), assets_root=Path()
    )

    assert tracker is not None
    assert (tracker.benchmark_id, tracker.total) == (benchmark.id, 1)


def test_aggregate_route_must_be_an_absolute_route() -> None:
    with pytest.raises(ValueError, match="aggregate_route must be an absolute route path"):
        _benchmark(aggregate_route="benchmarks/alpha/aggregate")


def _successful_case(case_id: int) -> str:
    return case_execution.compact_json(
        case_execution.case_execution_payload(
            case_id,
            encode_candidate_invocation(f"answer {case_id}", "stop", None),
            [{"verdict": "PASS"}],
        )
    )


def _successful_observation(case_id: int) -> CaseExecutionObservation:
    raw = _successful_case(case_id)
    return CaseExecutionObservation(raw=raw, outcome=case_execution_outcome(raw))


def test_terminal_tracker_deduplicates_successes_rejects_malformed_rows_and_is_bounded() -> None:
    tracker = EvaluationProgressTracker(benchmark_id="alpha", total=2)

    assert tracker.record_case_execution(_successful_observation(1))
    assert not tracker.record_case_execution(_successful_observation(1))
    assert not tracker.record_case_execution(cast(Any, "not-json"))
    assert tracker.record_candidate_failure()
    assert not tracker.record_candidate_failure()

    assert tracker.completed == 2
    assert tracker.candidate_failures == 1
    assert tracker.case_executions == (_successful_case(1),)


def test_complete_snapshots_use_selected_order_and_the_shared_scorer() -> None:
    records: list[tuple[str, dict[str, LogScalar]]] = []
    scorer_inputs: list[tuple[int | str, ...]] = []

    def grade(raw: str) -> IndexedCaseResult:
        case_id = int(json.loads(raw)["case_id"])
        score = {1: 0.8, 2: 0.2}[case_id]
        return IndexedCaseResult(case_id - 1, _projected_case(case_id, score))

    def scorer(cases: Sequence[CaseResult]) -> CandidateScore:
        scorer_inputs.append(tuple(case.case_id for case in cases))
        return _mean_score(cases)

    benchmark = _benchmark(case_count=2, grade_case=grade, score_cases=scorer)
    adapter = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,)))
    scope = adapter.open_run_scope(
        render(_aggregate_call(_route(benchmark), text("aggregate:2"))),
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    with scope:
        case_execution._case_execution(_case_request(2))
        case_execution._case_execution(_case_request(1))

    assert scorer_inputs == [(2,), (1, 2)]
    assert records == [
        (
            "evaluation progress",
            {
                "screamingface.event.schema": "screamingface.evaluation-progress.v1",
                "cases.total": 2,
                "cases.completed": 1,
                "cases.graded": 1,
                "cases.failed": 0,
                "cases.refused": 0,
                "score.provisional": 0.2,
                "score.coverage": 0.5,
            },
        ),
        (
            "evaluation progress",
            {
                "screamingface.event.schema": "screamingface.evaluation-progress.v1",
                "cases.total": 2,
                "cases.completed": 2,
                "cases.graded": 2,
                "cases.failed": 0,
                "cases.refused": 0,
                "score.provisional": 0.5,
                "score.coverage": 1.0,
            },
        ),
    ]


def test_candidate_failure_emits_one_terminal_failed_snapshot() -> None:
    benchmark = _benchmark(case_count=1)
    records: list[tuple[str, dict[str, LogScalar]]] = []
    adapter = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,)))
    scope = adapter.open_run_scope(
        render(_aggregate_call(_route(benchmark), text("aggregate:1"))),
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    with scope:
        record_candidate_failure()
        record_candidate_failure()

    assert records == [
        (
            "evaluation progress",
            {
                "screamingface.event.schema": "screamingface.evaluation-progress.v1",
                "cases.total": 1,
                "cases.completed": 1,
                "cases.graded": 0,
                "cases.failed": 1,
                "cases.refused": 0,
                "score.provisional": None,
                "score.coverage": 0.0,
            },
        )
    ]


def test_identified_terminal_reconciles_an_anonymous_failure_at_capacity() -> None:
    benchmark = _benchmark(case_count=2)
    records: list[tuple[str, dict[str, LogScalar]]] = []
    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        render(_aggregate_call(_route(benchmark), text("aggregate:2"))),
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    with scope:
        record_candidate_failure()
        record_candidate_failure()
        case_execution._case_execution(_case_request(1))

    assert [attributes["cases.completed"] for _, attributes in records] == [1, 2, 2]
    assert records[-1][1]["cases.graded"] == 1
    assert records[-1][1]["cases.failed"] == 1


def test_url4_stringified_integer_case_id_uses_the_integer_projection() -> None:
    benchmark = _benchmark(case_count=1)
    records: list[tuple[str, dict[str, LogScalar]]] = []
    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        render(_aggregate_call(_route(benchmark), text("aggregate:1"))),
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    with scope:
        case_execution._case_execution(_case_request("1"))

    assert records[0][1]["cases.graded"] == 1
    assert records[0][1]["score.provisional"] == 1.0


@pytest.mark.parametrize(
    ("projected", "graded", "failed", "refused", "score"),
    [
        (
            refused_case_result(
                selected_case=SelectedCase(case_id=1, input="question 1", metadata={}),
                refusal="I cannot answer.",
                grade={"method": "test", "score": 0.4, "metrics": {}, "checks": []},
            ),
            1,
            0,
            1,
            0.4,
        ),
        (
            failed_case_result(
                selected_case=SelectedCase(case_id=1, input="question 1", metadata={}),
                failures=[
                    {
                        "stage": "grading",
                        "code": "grading_failed",
                        "message": "grading failed",
                        "retryable": None,
                        "case_id": 1,
                        "metadata": {},
                    }
                ],
                grade={"method": "test", "score": None, "metrics": {}, "checks": []},
            ),
            0,
            1,
            0,
            None,
        ),
    ],
)
def test_snapshot_counts_follow_the_projected_case_contract(
    projected: CaseResult,
    graded: int,
    failed: int,
    refused: int,
    score: float | None,
) -> None:
    benchmark = _benchmark(
        case_count=1,
        grade_case=lambda _raw: IndexedCaseResult(0, projected),
    )
    records: list[tuple[str, dict[str, LogScalar]]] = []
    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        render(_aggregate_call(_route(benchmark), text("aggregate:1"))),
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    with scope:
        case_execution._case_execution(_case_request(1))

    attributes = records[0][1]
    assert attributes["cases.graded"] == graded
    assert attributes["cases.failed"] == failed
    assert attributes["cases.refused"] == refused
    assert attributes["score.provisional"] == score


def test_scorer_failure_suppresses_only_that_snapshot_and_later_scoring_recovers() -> None:
    records: list[tuple[str, dict[str, LogScalar]]] = []

    def scorer(cases: Sequence[CaseResult]) -> CandidateScore:
        if len(cases) == 1:
            raise RuntimeError("private scorer detail")
        return CandidateScore(score=0.5, metrics={})

    benchmark = _benchmark(case_count=2, score_cases=scorer)
    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        render(_aggregate_call(_route(benchmark), text("aggregate:2"))),
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    with scope:
        for case_id in (1, 2):
            case_execution._case_execution(_case_request(case_id))

    assert [attributes["score.provisional"] for _, attributes in records] == [None, 0.5]


def _case_request(case_id: int | str) -> Request:
    return Request(
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
