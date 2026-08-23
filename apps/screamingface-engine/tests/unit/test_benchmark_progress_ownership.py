"""Ownership isolation for syntax-discovered Evaluation progress (OME-932)."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence

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
    scored_case_result,
)
from screamingface_engine.benchmarks.contract import CaseResult, encode_candidate_invocation
from screamingface_engine.benchmarks.run_logs import (
    BenchmarkRunLogAdapter,
    emit_benchmark_run_log,
)
from screamingface_engine.run_log_contract import LogScalar
from url4 import RelExpr, render, text
from url4.peer.server import Request


def _benchmark(benchmark_id: str, *, progress: bool) -> Benchmark:
    route = f"/benchmarks/{benchmark_id}/v1/aggregate"

    def grade(raw: str) -> IndexedCaseResult:
        case_id = int(json.loads(raw)["case_id"])
        result = scored_case_result(
            selected_case=SelectedCase(case_id=case_id, input="question", metadata={}),
            output="answer",
            finish_reason="stop",
            grade={"method": "test", "score": 1.0, "metrics": {}, "checks": []},
        )
        return IndexedCaseResult(0, result)

    def score(_cases: Sequence[CaseResult]) -> CandidateScore:
        return CandidateScore(score=1.0, metrics={})

    return Benchmark(
        id=benchmark_id,
        title=f"{benchmark_id} evaluation",
        description="A progress ownership fixture.",
        revision="v1",
        case_count=1,
        build=lambda _selected: text("unused"),
        evaluation=(
            BenchmarkEvaluation(
                aggregate_route=route,
                bind=lambda _root, _selected: BoundEvaluation(grade, score),
            )
            if progress
            else None
        ),
    )


def _expression(benchmark: Benchmark) -> str:
    assert benchmark.evaluation is not None
    return render(
        RelExpr(
            path=benchmark.evaluation.aggregate_route,
            context="[]",
            intent=text("aggregate:1"),
        )
    )


def _case_request() -> Request:
    return Request(
        path=case_execution.CASE_EXECUTION_ROUTE,
        context=json.dumps(
            {
                "case_id": 1,
                "candidate_invocation": encode_candidate_invocation("answer", "stop", None),
                "grading": [{"verdict": "PASS"}],
            }
        ),
        intent="preserve",
        params={},
    )


def test_progress_snapshot_does_not_claim_generic_benchmark_log_ownership(
    caplog: pytest.LogCaptureFixture,
) -> None:
    progress = _benchmark("alpha", progress=True)
    other = _benchmark("beta", progress=False)
    records: list[tuple[str, dict[str, LogScalar]]] = []

    def emit(body: str, attributes: Mapping[str, LogScalar]) -> None:
        records.append((body, dict(attributes)))

    adapter = BenchmarkRunLogAdapter(BenchmarkRegistry((progress, other)))
    caplog.set_level(logging.WARNING)
    scope = adapter.open_run_scope(_expression(progress), emit)
    assert scope is not None

    with scope:
        case_execution._case_execution(_case_request())
        emit_benchmark_run_log("beta", "authoritative", {"observed": 2})

    assert [body for body, _attributes in records] == ["evaluation progress", "authoritative"]
    assert "conflicting Benchmark run Log claims" not in caplog.text
