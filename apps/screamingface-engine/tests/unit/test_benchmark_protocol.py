"""The shared Benchmark protocol owns the outer Case-to-Aggregation lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.case_execution import (
    CASE_EXECUTION_SCHEMA,
    install_case_execution,
)
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.definition import Benchmark
from screamingface_engine.benchmarks.draco.definition import DRACO, JUDGE_MODEL
from screamingface_engine.benchmarks.healthbench.definition import HEALTHBENCH_WORST30
from screamingface_engine.benchmarks.ifeval.definition import IFEVAL
from screamingface_engine.benchmarks.protocol import (
    build_evaluation_protocol,
    preserve_candidate_outcome,
)
from url4 import RelExpr, Text, expr, render, src, struct
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


def test_public_catalogue_contains_exactly_the_five_product_benchmarks() -> None:
    # OME-903 added the professional board beside the worst-30% challenge; the 3-pass DRACO
    # board joined the canonical one; all are complete, independently meaningful benchmark
    # identities over one baked answer key.
    assert tuple(benchmark.id for benchmark in BUILTIN_BENCHMARKS) == (
        "draco",
        "draco-3pass",
        "healthbench-professional",
        "healthbench-worst30",
        "ifeval",
    )


def test_canonical_draco_limit_changes_cases_only_not_grading_strength() -> None:
    full = render(DRACO.build(DRACO.case_count))
    one_case = render(DRACO.build(1))

    assert DRACO.id == "draco"
    assert DRACO.case_count == 100
    assert full.count("/" + JUDGE_MODEL) == 5
    assert one_case.count("/" + JUDGE_MODEL) == 5
    assert "iteration.slice=0:1" not in full
    # Exactly one slice is the outer Case selection; criteria remain unsliced.
    assert one_case.count("iteration.slice=0:1") == 1


def test_canonical_draco_judge_passes_have_stable_independent_cache_slots() -> None:
    expression = render(DRACO.build(1))

    assert expression.count("web_search=false") == 5
    for seed in range(1, 6):
        assert expression.count(f"&seed={seed}") == 1


@pytest.mark.asyncio
async def test_protocol_preserves_selected_order_and_collects_a_case_failure() -> None:
    node = Url4Node("benchmark-protocol")
    node.data(
        "/example/cases",
        json.dumps(
            [
                {"id": 11, "input": "first"},
                {"id": 22, "input": "second"},
                {"id": 33, "input": "unselected"},
            ]
        ),
        media_type="application/json",
    )

    @node.endpoint("/example/evaluate-case")
    def evaluate_case(request: Request) -> str:
        if request.intent == "22":
            raise ResolutionError("candidate failed", code="candidate_failed", permanent=True)
        return json.dumps({"case_id": int(request.intent), "output": request.context})

    @node.endpoint("/example/aggregate")
    def aggregate(request: Request) -> str:
        return json.dumps(
            {
                "intent": request.intent,
                "case_evaluations": json.loads(request.context),
            }
        )

    protocol = build_evaluation_protocol(
        cases_route="/example/cases",
        case_evaluation=RelExpr(
            path="/example/evaluate-case",
            context="$item.input",
            intent=Text("$item.id"),
        ),
        selected_case_count=2,
        available_case_count=3,
        aggregate_route="/example/aggregate",
    )

    result = json.loads((await node.evaluate(render(protocol))).text)

    assert result == {
        "intent": "aggregate:2",
        "case_evaluations": [
            {"case_id": 11, "output": "first"},
            {
                "error": {
                    "kind": "ResolutionError",
                    "message": "candidate failed",
                    "code": "candidate_failed",
                    "retryable": False,
                }
            },
        ],
    }


@pytest.mark.asyncio
async def test_protocol_evaluates_only_one_complete_case_at_a_time() -> None:
    node = Url4Node("benchmark-sequential-cases")
    node.data(
        "/example/cases",
        json.dumps([{"id": "case-1"}, {"id": "case-2"}, {"id": "case-3"}]),
        media_type="application/json",
    )
    active_cases: set[str] = set()
    active_branches = max_active_cases = max_active_branches = 0

    @node.endpoint("/example/case-branch")
    async def case_branch(request: Request) -> str:
        nonlocal active_branches, max_active_branches, max_active_cases
        active_cases.add(request.context)
        active_branches += 1
        max_active_cases = max(max_active_cases, len(active_cases))
        max_active_branches = max(max_active_branches, active_branches)
        try:
            await asyncio.sleep(0.01)
            return request.intent
        finally:
            active_branches -= 1

    @node.endpoint("/example/complete-case")
    def complete_case(request: Request) -> str:
        payload = json.loads(request.context)
        active_cases.remove(payload["case_id"])
        return json.dumps({"case_id": payload["case_id"]})

    @node.endpoint("/example/aggregate")
    def aggregate(request: Request) -> str:
        return request.context

    case_evaluation = expr(
        src(
            RelExpr(path="/example/case-branch", context="$item.id", intent=Text("left")),
            name="left",
            weight=0.0,
        ),
        src(
            RelExpr(path="/example/case-branch", context="$item.id", intent=Text("right")),
            name="right",
            weight=0.0,
        ),
        src(
            RelExpr(
                path="/example/complete-case",
                context=render(struct({"case_id": "$item.id", "left": "$left", "right": "$right"})),
                intent=Text(""),
            ),
            name="completed",
            weight=0.0,
        ),
        intent=Text("$completed"),
    )
    protocol = build_evaluation_protocol(
        cases_route="/example/cases",
        case_evaluation=case_evaluation,
        selected_case_count=3,
        available_case_count=3,
        aggregate_route="/example/aggregate",
    )
    rendered = render(protocol)

    await node.evaluate(rendered)

    # INVARIANT: whole Cases are serial, while independent work inside one Case stays parallel.
    assert max_active_cases == 1
    assert max_active_branches == 2
    assert "iteration.concurrency=1" in rendered


@pytest.mark.asyncio
async def test_case_execution_preserves_candidate_invocation_when_grading_fails() -> None:
    node = Url4Node("benchmark-case-execution")

    @node.endpoint("/candidate")
    def candidate(_request: Request) -> str:
        return encode_candidate_invocation("", "content_filter", "exact refusal")

    @node.endpoint("/grade")
    def grade(_request: Request) -> str:
        raise ResolutionError("checker unavailable", code="checker_failed", permanent=True)

    install_case_execution(node)

    protected = preserve_candidate_outcome(
        candidate_invocation=RelExpr(path="/candidate", context="question", intent=Text("")),
        grading=RelExpr(
            path="/grade",
            context="$candidate_invocation",
            intent=Text(""),
        ),
        case_id="case-1",
    )

    result = json.loads((await node.evaluate(render(protected))).text)

    assert result == {
        "schema": CASE_EXECUTION_SCHEMA,
        "case_id": "case-1",
        "candidate_invocation": encode_candidate_invocation("", "content_filter", "exact refusal"),
        "grading": [
            {
                "error": {
                    "kind": "ResolutionError",
                    "message": "checker unavailable",
                    "code": "checker_failed",
                    "retryable": False,
                }
            }
        ],
    }


def test_protocol_rejects_an_impossible_case_selection() -> None:
    with pytest.raises(ValueError, match="selected_case_count"):
        build_evaluation_protocol(
            cases_route="/example/cases",
            case_evaluation=RelExpr(path="/example/evaluate-case"),
            selected_case_count=4,
            available_case_count=3,
            aggregate_route="/example/aggregate",
        )


@pytest.mark.parametrize(
    ("benchmark", "expected_sha256"),
    (
        (DRACO, "7fdef3acb7f97ff14d91c1c7eb1937bc58681367555cfa4206d615cb4bb69f87"),
        (IFEVAL, "c272779623671772ad8c2629e320e283837f34e3b270c693643285174794e4f8"),
        (
            HEALTHBENCH_WORST30,
            "bc4c584c826b5fa40ff0b563b4470cb89790712f08e92f0c0aeff151f3210102",
        ),
    ),
)
def test_canonical_benchmark_url4_is_pinned_byte_for_byte(
    benchmark: Benchmark, expected_sha256: str
) -> None:
    url4 = render(benchmark.build(benchmark.case_count))

    assert hashlib.sha256(url4.encode()).hexdigest() == expected_sha256


def test_canonical_ifeval_binds_the_exact_selected_count_for_aggregation() -> None:
    assert "!'aggregate:2'" in render(IFEVAL.build(2))


@pytest.mark.asyncio
async def test_protocol_resolves_shared_bindings_before_case_iteration() -> None:
    node = Url4Node("benchmark-bindings")
    node.data(
        "/example/cases",
        json.dumps([{"id": 1, "input": "case"}]),
        media_type="application/json",
    )

    @node.endpoint("/example/evaluate-case")
    def evaluate_case(request: Request) -> str:
        return request.context

    @node.endpoint("/example/aggregate")
    def aggregate(request: Request) -> str:
        return request.context

    protocol = build_evaluation_protocol(
        cases_route="/example/cases",
        case_evaluation=RelExpr(
            path="/example/evaluate-case", context="$shared", intent=Text("$item.id")
        ),
        selected_case_count=1,
        available_case_count=1,
        aggregate_route="/example/aggregate",
        bindings=(src(Text("resolved-once"), name="shared", weight=0.0),),
    )

    assert json.loads((await node.evaluate(render(protocol))).text) == ["resolved-once"]
