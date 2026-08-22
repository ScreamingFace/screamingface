"""Exact, fail-open terminal progress discovery and accounting (OME-932)."""

from __future__ import annotations

import json

import pytest

from screamingface_engine.benchmarks import (
    Benchmark,
    BenchmarkRegistry,
    candidate_adapter,
    case_execution,
)
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.progress import (
    EvaluationProgressTracker,
    discover_evaluation_progress,
)
from url4 import Node, RelExpr, RelUrl, expr, render, text
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


def _benchmark(
    benchmark_id: str = "alpha",
    *,
    case_count: int = 100,
    aggregate_route: str = "/benchmarks/alpha/v1/aggregate",
) -> Benchmark:
    return Benchmark(
        id=benchmark_id,
        title="Progress benchmark",
        description="A terminal progress discovery fixture.",
        revision="progress-v1",
        case_count=case_count,
        build=lambda _selected: text("unused"),
        aggregate_route=aggregate_route,
    )


def _aggregate_call(route: str, intent: Node) -> RelExpr:
    return RelExpr(path=route, context="[]", intent=intent)


@pytest.mark.parametrize("selected", [1, 10, 100])
def test_exact_registered_aggregate_call_discovers_selected_total(selected: int) -> None:
    benchmark = _benchmark()
    rendered = render(
        _aggregate_call(benchmark.aggregate_route or "", text(f"aggregate:{selected}"))
    )

    tracker = discover_evaluation_progress(BenchmarkRegistry((benchmark,)), rendered)

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
    assert discover_evaluation_progress(BenchmarkRegistry((_benchmark(),)), rendered) is None


def test_multiple_registered_aggregate_calls_are_ambiguous_and_inert() -> None:
    benchmark = _benchmark()
    aggregate = benchmark.aggregate_route or ""
    rendered = render(
        expr(
            _aggregate_call(aggregate, text("aggregate:10")),
            _aggregate_call(aggregate, text("aggregate:10")),
            intent=text("$1"),
        )
    )

    assert discover_evaluation_progress(BenchmarkRegistry((benchmark,)), rendered) is None


def test_same_aggregate_route_declared_by_multiple_benchmarks_is_ambiguous_and_inert() -> None:
    alpha = _benchmark("alpha")
    beta = _benchmark("beta")
    rendered = render(_aggregate_call(alpha.aggregate_route or "", text("aggregate:1")))

    assert discover_evaluation_progress(BenchmarkRegistry((alpha, beta)), rendered) is None


def test_every_builtin_protocol_declares_and_discovers_its_exact_aggregate_route() -> None:
    for benchmark in BUILTIN_BENCHMARKS:
        assert benchmark.aggregate_route is not None
        tracker = discover_evaluation_progress(BUILTIN_BENCHMARKS, render(benchmark.protocol(1)))
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


def test_terminal_tracker_deduplicates_successes_rejects_malformed_rows_and_is_bounded() -> None:
    tracker = EvaluationProgressTracker(benchmark_id="alpha", total=2)

    assert tracker.record_case_execution(_successful_case(1))
    assert not tracker.record_case_execution(_successful_case(1))
    assert not tracker.record_case_execution("not-json")
    assert tracker.record_candidate_failure()
    assert not tracker.record_candidate_failure()

    assert tracker.completed == 2
    assert tracker.candidate_failures == 1
    assert tracker.case_executions == (_successful_case(1),)


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
