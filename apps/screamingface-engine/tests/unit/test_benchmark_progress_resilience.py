"""Fail-open, privacy, and isolation proofs for Evaluation progress (OME-932)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping

import pytest

from screamingface_engine.benchmarks import (
    Benchmark,
    BenchmarkRegistry,
    candidate_adapter,
    case_execution,
)
from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    scored_case_result,
)
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.progress import EvaluationProgressTracker
from screamingface_engine.benchmarks.run_logs import (
    BenchmarkRunLogAdapter,
    register_case_projection,
)
from screamingface_engine.run_log_contract import LogScalar
from url4 import RelExpr, render, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


def _benchmark(case_count: int = 2) -> Benchmark:
    return Benchmark(
        id="alpha",
        title="Progress benchmark",
        description="A resilience fixture.",
        revision="progress-v1",
        case_count=case_count,
        build=lambda _selected: text("unused"),
        aggregate_route="/benchmarks/alpha/v1/aggregate",
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


def _projected(case_id: int, score: float):
    return scored_case_result(
        selected_case=SelectedCase(case_id=case_id, input=f"question {case_id}", metadata={}),
        output=f"answer {case_id}",
        finish_reason="stop",
        grade={"method": "test", "score": score, "metrics": {}, "checks": []},
    )


def _scorer(cases) -> CandidateScore:
    grade = cases[0].grade
    assert grade is not None and grade.score is not None
    return CandidateScore(score=float(grade.score), metrics={})


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


def test_registration_failure_is_fail_open_and_privacy_bounded(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    benchmark = _benchmark(1)
    caplog.set_level(logging.WARNING)

    def discard_log(body: str, attributes: Mapping[str, LogScalar]) -> None:
        del body, attributes

    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        _rendered(1), discard_log
    )
    assert scope is not None

    def fail_registration(self, *args, **kwargs):
        del self, args, kwargs
        raise RuntimeError("private Case and rubric")

    monkeypatch.setattr(
        EvaluationProgressTracker,
        "register_case_projection",
        fail_registration,
    )
    with scope:
        register_case_projection(
            benchmark.id,
            case_id=1,
            selected_index=0,
            grade_case=lambda _raw: _projected(1, 1.0),
            scorer=_scorer,
        )

    assert "Benchmark progress observation failed (RuntimeError)" in caplog.text
    assert "private Case" not in caplog.text
    assert "rubric" not in caplog.text


def test_projector_failure_suppresses_snapshot_and_preserves_case_return(
    caplog: pytest.LogCaptureFixture,
) -> None:
    benchmark = _benchmark(1)
    records: list[tuple[str, dict[str, LogScalar]]] = []
    caplog.set_level(logging.WARNING)
    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        _rendered(1),
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    def fail_projection(_raw: str):
        raise RuntimeError("private answer and rubric")

    with scope:
        register_case_projection(
            benchmark.id,
            case_id=1,
            selected_index=0,
            grade_case=fail_projection,
            scorer=_scorer,
        )
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
        register_case_projection(
            benchmark.id,
            case_id=1,
            selected_index=0,
            grade_case=lambda _raw: _projected(1, 1.0),
            scorer=_scorer,
        )
        case_execution._case_execution(_request(1))
        case_execution._case_execution(_request("1"))

    assert len(records) == 1
    assert records[0][1]["cases.completed"] == 1


def test_non_finite_provisional_score_is_suppressed() -> None:
    benchmark = _benchmark(1)
    records: list[tuple[str, dict[str, LogScalar]]] = []
    scope = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,))).open_run_scope(
        _rendered(1),
        lambda body, attributes: records.append((body, dict(attributes))),
    )
    assert scope is not None

    with scope:
        register_case_projection(
            benchmark.id,
            case_id=1,
            selected_index=0,
            grade_case=lambda _raw: _projected(1, 1.0),
            scorer=lambda _cases: CandidateScore(score=float("nan"), metrics={}),
        )
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
        register_case_projection(
            benchmark.id,
            case_id=1,
            selected_index=0,
            grade_case=lambda _raw: _projected(1, 1.0),
            scorer=_scorer,
        )
        result = case_execution._case_execution(_request(1))

    assert json.loads(result)["case_id"] == 1
    assert "Benchmark run Log adapter emission failed (RuntimeError)" in caplog.text
    assert "private prompt" not in caplog.text


@pytest.mark.asyncio
async def test_concurrent_evaluations_keep_independent_progress_and_scores() -> None:
    benchmark = _benchmark(1)
    adapter = BenchmarkRunLogAdapter(BenchmarkRegistry((benchmark,)))

    async def evaluate(case_id: int, score: float):
        records: list[tuple[str, dict[str, LogScalar]]] = []
        scope = adapter.open_run_scope(
            _rendered(1),
            lambda body, attributes: records.append((body, dict(attributes))),
        )
        assert scope is not None
        with scope:
            register_case_projection(
                benchmark.id,
                case_id=case_id,
                selected_index=0,
                grade_case=lambda _raw: _projected(case_id, score),
                scorer=_scorer,
            )
            await asyncio.sleep(0)
            case_execution._case_execution(_request(case_id))
        return records

    left, right = await asyncio.gather(evaluate(1, 0.2), evaluate(2, 0.8))

    assert left[0][1]["score.provisional"] == 0.2
    assert right[0][1]["score.provisional"] == 0.8


def test_aggregate_route_is_private_execution_metadata_not_catalogue_data() -> None:
    for benchmark in BUILTIN_BENCHMARKS:
        assert "aggregate_route" not in benchmark.resource(1)
