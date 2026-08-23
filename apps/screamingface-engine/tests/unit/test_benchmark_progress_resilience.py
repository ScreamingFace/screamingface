"""Fail-open, privacy, and isolation proofs for Evaluation progress (OME-932)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence

import pytest

from screamingface_engine.benchmarks import (
    Benchmark,
    BenchmarkEvaluation,
    BenchmarkRegistry,
    BoundEvaluation,
    IndexedCaseResult,
    candidate_adapter,
    case_execution,
)
from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    scored_case_result,
)
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.contract import CaseResult, encode_candidate_invocation
from screamingface_engine.benchmarks.run_logs import BenchmarkRunLogAdapter
from screamingface_engine.run_log_contract import LogScalar
from url4 import RelExpr, render, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

type CaseEvaluator = Callable[[str], IndexedCaseResult]
type CaseScorer = Callable[[Sequence[CaseResult]], CandidateScore]


def _projected(case_id: int, score: float) -> CaseResult:
    return scored_case_result(
        selected_case=SelectedCase(case_id=case_id, input=f"question {case_id}", metadata={}),
        output=f"answer {case_id}",
        finish_reason="stop",
        grade={"method": "test", "score": score, "metrics": {}, "checks": []},
    )


def _default_grade(raw: str) -> IndexedCaseResult:
    case_id = int(json.loads(raw)["case_id"])
    return IndexedCaseResult(case_id - 1, _projected(case_id, 1.0))


def _scorer(cases: Sequence[CaseResult]) -> CandidateScore:
    grade = cases[0].grade
    assert grade is not None and grade.score is not None
    return CandidateScore(score=float(grade.score), metrics={})


def _benchmark(
    case_count: int = 2,
    *,
    grade_case: CaseEvaluator = _default_grade,
    score_cases: CaseScorer = _scorer,
    bind: Callable[[int], BoundEvaluation] | None = None,
) -> Benchmark:
    evaluation = BenchmarkEvaluation(
        aggregate_route="/benchmarks/alpha/v1/aggregate",
        bind=(
            (lambda _root, selected: bind(selected))
            if bind is not None
            else lambda _root, _selected: BoundEvaluation(grade_case, score_cases)
        ),
    )
    return Benchmark(
        id="alpha",
        title="Progress benchmark",
        description="A resilience fixture.",
        revision="progress-v1",
        case_count=case_count,
        build=lambda _selected: text("unused"),
        evaluation=evaluation,
    )


def _rendered(total: int) -> str:
    return render(
        RelExpr(
            path="/benchmarks/alpha/v1/aggregate",
            context="[]",
            intent=text(f"aggregate:{total}"),
        )
    )


def _request(case_id: int | str) -> Request:
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


@pytest.mark.parametrize(
    ("intent", "params", "code"),
    [
        ("", {"web_search": "false"}, "candidate_contract_error"),
        ("/provider/model(input)!answer", {}, "candidate_policy_invalid"),
    ],
)
@pytest.mark.asyncio
async def test_pre_execution_candidate_contract_errors_are_terminal_failures(
    monkeypatch: pytest.MonkeyPatch,
    intent: str,
    params: dict[str, str],
    code: str,
) -> None:
    observed: list[None] = []
    monkeypatch.setattr(
        candidate_adapter,
        "record_candidate_failure",
        lambda: observed.append(None),
    )
    invocation = candidate_adapter._CandidateInvocation(Url4Node())

    with pytest.raises(ResolutionError) as raised:
        await invocation(Request("/benchmarks/candidate", "question", intent, params))

    assert raised.value.code == code
    assert observed == [None]


def test_case_execution_notifies_only_after_constructing_the_exact_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []
    monkeypatch.setattr(case_execution, "record_successful_case_execution", observed.append)
    invocation = encode_candidate_invocation("answer", "stop", None)
    request = Request(
        path=case_execution.CASE_EXECUTION_ROUTE,
        context=json.dumps(
            {
                "case_id": 7,
                "candidate_invocation": invocation,
                "grading": [{"verdict": "PASS"}],
            }
        ),
        intent="preserve",
        params={},
    )

    result = case_execution._case_execution(request)

    assert observed == [result]
    assert result == case_execution.compact_json(
        case_execution.case_execution_payload(7, invocation, [{"verdict": "PASS"}])
    )


@pytest.mark.asyncio
async def test_candidate_exception_records_failure_and_reraises_the_same_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = ResolutionError("candidate failed", code="candidate_failed", permanent=True)
    observed: list[None] = []

    async def fail_candidate(_node: Url4Node, _intent: str, _context: str) -> str:
        raise failure

    monkeypatch.setattr(candidate_adapter, "evaluate_candidate_recipe", fail_candidate)
    monkeypatch.setattr(
        candidate_adapter,
        "record_candidate_failure",
        lambda: observed.append(None),
    )
    invocation = candidate_adapter._CandidateInvocation(Url4Node())
    request = Request(
        path="/benchmarks/candidate",
        context="question",
        intent="/provider/model(input)!answer",
        params={"web_search": "false"},
    )

    with pytest.raises(ResolutionError) as raised:
        await invocation(request)

    assert raised.value is failure
    assert observed == [None]


def test_binding_failure_is_fail_open_and_privacy_bounded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    def fail_binding(_selected: int) -> BoundEvaluation:
        raise RuntimeError("private Case and rubric")

    benchmark = _benchmark(1, bind=fail_binding)

    def discard_log(body: str, attributes: Mapping[str, LogScalar]) -> None:
        del body, attributes

    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        _rendered(1), discard_log
    )

    assert scope is not None
    assert "Benchmark Evaluation binding failed (RuntimeError)" in caplog.text
    assert "private Case" not in caplog.text
    assert "rubric" not in caplog.text


def test_projector_failure_suppresses_snapshot_and_preserves_case_return(
    caplog: pytest.LogCaptureFixture,
) -> None:
    records: list[tuple[str, dict[str, LogScalar]]] = []
    caplog.set_level(logging.WARNING)

    def fail_projection(_raw: str) -> IndexedCaseResult:
        raise RuntimeError("private answer and rubric")

    benchmark = _benchmark(1, grade_case=fail_projection)
    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        _rendered(1),
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    with scope:
        result = case_execution._case_execution(_request(1))

    assert json.loads(result)["case_id"] == 1
    assert records == []
    assert "Benchmark progress observation failed (RuntimeError)" in caplog.text
    assert "private answer" not in caplog.text


def test_integer_and_string_forms_of_one_case_are_terminal_once() -> None:
    benchmark = _benchmark(2)
    records: list[tuple[str, dict[str, LogScalar]]] = []
    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        _rendered(2),
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    with scope:
        case_execution._case_execution(_request(1))
        case_execution._case_execution(_request("1"))

    assert len(records) == 1
    assert records[0][1]["cases.completed"] == 1


def test_non_finite_provisional_score_is_suppressed() -> None:
    benchmark = _benchmark(
        1,
        score_cases=lambda _cases: CandidateScore(score=float("nan"), metrics={}),
    )
    records: list[tuple[str, dict[str, LogScalar]]] = []
    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        _rendered(1),
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    with scope:
        case_execution._case_execution(_request(1))

    assert records[0][1]["cases.graded"] == 1
    assert records[0][1]["score.provisional"] is None


def test_sink_failure_cannot_change_case_return_or_log_private_material(
    caplog: pytest.LogCaptureFixture,
) -> None:
    benchmark = _benchmark(1)
    caplog.set_level(logging.WARNING)

    def fail_sink(body: str, attributes: Mapping[str, LogScalar]) -> None:
        del body, attributes
        raise RuntimeError("private prompt and rubric must not leak")

    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        _rendered(1), fail_sink
    )
    assert scope is not None

    with scope:
        result = case_execution._case_execution(_request(1))

    assert json.loads(result)["case_id"] == 1
    assert "Benchmark run Log adapter emission failed (RuntimeError)" in caplog.text
    assert "private prompt" not in caplog.text


@pytest.mark.asyncio
async def test_concurrent_evaluations_keep_independent_progress_and_scores() -> None:
    scores = {1: 0.2, 2: 0.8}

    def grade(raw: str) -> IndexedCaseResult:
        case_id = int(json.loads(raw)["case_id"])
        return IndexedCaseResult(0, _projected(case_id, scores[case_id]))

    benchmark = _benchmark(2, grade_case=grade)
    adapter = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,)))

    async def evaluate(case_id: int) -> list[tuple[str, dict[str, LogScalar]]]:
        records: list[tuple[str, dict[str, LogScalar]]] = []
        scope = adapter.open_run_scope(
            _rendered(1),
            lambda body, attributes: records.append((body, dict(attributes))),
        )
        assert scope is not None
        with scope:
            await asyncio.sleep(0)
            case_execution._case_execution(_request(case_id))
        return records

    left, right = await asyncio.gather(evaluate(1), evaluate(2))

    assert left[0][1]["score.provisional"] == 0.2
    assert right[0][1]["score.provisional"] == 0.8


def test_evaluation_metadata_is_private_not_catalogue_data() -> None:
    for benchmark in BUILTIN_BENCHMARKS:
        resource = benchmark.resource(1)
        assert "aggregate_route" not in resource
        assert "evaluation" not in resource
