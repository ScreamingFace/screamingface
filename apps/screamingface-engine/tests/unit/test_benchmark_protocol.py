"""The shared Benchmark protocol owns the outer Case-to-Aggregation lifecycle."""

from __future__ import annotations

# OME-932 (owner-approved): early graded-results transport is additive; grading
# and semantic revision pins remain unchanged to preserve ranked submissions.
import asyncio
import hashlib
import json
from dataclasses import replace

import httpx
import pytest

from screamingface_engine.app import create_app
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS, BUILTIN_DEPLOYMENT
from screamingface_engine.benchmarks.case_evaluation import case_evaluation_code
from screamingface_engine.benchmarks.case_selection import install_cases
from screamingface_engine.benchmarks.code_calls import run_case_evaluation
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.definition import Benchmark
from screamingface_engine.benchmarks.graded_answer import GRADED_ANSWER_SCHEMA
from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT
from screamingface_engine.benchmarks.protocol import evaluation_protocol
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream
from url4 import CodeCall, Node, RelExpr, Text, render, src
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


def _protocol_node(name: str) -> Url4Node:
    node = Url4Node(name)
    return node


@pytest.mark.asyncio
async def test_the_public_catalogue_publishes_exactly_the_registered_benchmarks() -> None:
    """Every benchmark this deployment registers is discoverable on the wire, and nothing else is.

    WHY derived rather than a hand-typed tuple of ids (OME-1095): the deployment is the ONE
    place a benchmark is declared, and a second list here had to be edited by hand for every new
    benchmark — the exact cost this epic removes. What is load bearing is the relationship: what
    an operator registered is what a client can discover, under the ids it was registered
    with.

    WHAT THIS DOES NOT COVER: membership. Both sides derive from the same registrations, so
    deleting a benchmark from `builtins.py` makes it vanish from both and passes here. That a
    given benchmark is public is pinned in the benchmark's own definition test (or, for a
    local inspect Task, its Task test's row test).
    """

    registered = sorted(
        registration.benchmark.id for registration in BUILTIN_DEPLOYMENT.registrations
    )
    app = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=BUILTIN_BENCHMARKS,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://engine.test",
    ) as client:
        entries = (await client.get("/v1/benchmarks")).json()["data"]

    published = [entry["id"] for entry in entries]

    assert sorted(published) == registered


def _collected(call: CodeCall, name: str) -> object:
    """A code input as Python data: url4 hands rows over parsed, scalars as text."""

    value = call.input(name).value
    return json.loads(value) if isinstance(value, str) and value[:1] in "[{" else value


def _install_run_terminal(node: Url4Node) -> None:
    @node.code("/example/aggregate")
    def aggregate(call: CodeCall) -> str:
        return json.dumps(
            {
                "selected": call.input("selected").value,
                "case_evaluations": _collected(call, "evaluations"),
            }
        )


@pytest.mark.asyncio
async def test_protocol_preserves_selected_order_and_collects_a_case_failure() -> None:
    node = _protocol_node("benchmark-protocol")
    install_cases(
        node,
        "/example/cases",
        lambda: json.dumps(
            [
                {"id": 11, "input": "first"},
                {"id": 22, "input": "second"},
                {"id": 33, "input": "unselected"},
            ]
        ),
    )

    @node.endpoint("/example/evaluate-case")
    def evaluate_case(request: Request) -> str:
        if request.context == "second":
            raise ResolutionError("candidate failed", code="candidate_failed", permanent=True)
        return request.context

    # WHY a code terminal (spec R1/R4): the per-Case terminal is the body's code intent; it
    # reads the Case and the step result by name.
    @node.code("/example/case")
    def case(call: CodeCall) -> str:
        row = _collected(call, "case")
        assert isinstance(row, dict)
        return json.dumps({"case_id": row["id"], "output": call.input("evaluated").value})

    _install_run_terminal(node)
    protocol = evaluation_protocol(
        cases_route="/example/cases",
        steps=(
            src(
                RelExpr(path="/example/evaluate-case", context="$item.input", intent=Text("x")),
                name="evaluated",
                weight=0.0,
            ),
        ),
        case_terminal="/example/case",
        run_terminal="/example/aggregate",
        selected_case_count=2,
        available_case_count=3,
    )

    result = json.loads((await node.evaluate(render(protocol))).text)

    assert result == {
        "selected": "2",
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


def _branch(name: str) -> Node:
    return src(
        RelExpr(path="/example/case-branch", context="$item.id", intent=Text(name)),
        name=name,
        weight=0.0,
    )


@pytest.mark.asyncio
async def test_protocol_evaluates_only_one_complete_case_at_a_time() -> None:
    node = _protocol_node("benchmark-sequential-cases")
    install_cases(
        node,
        "/example/cases",
        lambda: json.dumps([{"id": "case-1"}, {"id": "case-2"}, {"id": "case-3"}]),
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

    @node.code("/example/complete-case")
    def complete_case(call: CodeCall) -> str:
        row = _collected(call, "case")
        assert isinstance(row, dict)
        active_cases.remove(row["id"])
        return json.dumps({"case_id": row["id"]})

    _install_run_terminal(node)
    protocol = evaluation_protocol(
        cases_route="/example/cases",
        steps=(_branch("left"), _branch("right")),
        case_terminal="/example/complete-case",
        run_terminal="/example/aggregate",
        selected_case_count=3,
        available_case_count=3,
    )
    rendered = render(protocol)

    await node.evaluate(rendered)

    # INVARIANT: whole Cases are serial, while independent work inside one Case stays parallel.
    assert max_active_cases == 1
    assert max_active_branches == 2
    assert "iteration.concurrency=1" in rendered


@pytest.mark.asyncio
async def test_case_execution_preserves_candidate_invocation_when_grading_fails() -> None:
    # WHY the code mount (spec §3.3): the retired protective iterate is now the
    # case-evaluation code's own per-Attempt catch; the row it writes is unchanged.
    node = Url4Node("benchmark-case-execution")
    invocation = encode_candidate_invocation("", "content_filter", "exact refusal")

    def check(_case_id: int, _invocation: str, _others: object) -> dict[str, object]:
        raise ResolutionError("checker unavailable", code="checker_failed", permanent=True)

    node.code("/case-evaluation")(
        case_evaluation_code(
            label="Example",
            check=check,
            build_case_grade=lambda case_id, records: {"case_id": case_id},
            observe_grading=False,
        )
    )

    result = json.loads(
        await run_case_evaluation(
            node, "/case-evaluation", case={"id": 7, "case_id": "7"}, attempts=[invocation]
        )
    )

    assert result == {
        "schema": GRADED_ANSWER_SCHEMA,
        "case_id": "7",
        "candidate_invocation": invocation,
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


@pytest.mark.asyncio
async def test_a_grader_bug_keeps_the_candidate_answer_in_the_row() -> None:
    """INVARIANT (spec §3.3): any grading failure, even a plain bug, never drops the answer."""

    node = Url4Node("benchmark-grader-bug")
    invocation = encode_candidate_invocation("B", "stop", None)

    def bundle(_case_id: int, _records: object) -> dict[str, object]:
        raise ZeroDivisionError("division by zero")

    node.code("/case-evaluation")(
        case_evaluation_code(
            label="Example",
            check=lambda case_id, _invocation, _others: {"case_id": case_id},
            build_case_grade=bundle,
            observe_grading=False,
        )
    )

    row = json.loads(
        await run_case_evaluation(
            node, "/case-evaluation", case={"id": 3, "case_id": "3"}, attempts=[invocation]
        )
    )

    assert row["candidate_invocation"] == invocation
    assert row["grading"] == [
        {"error": {"kind": "ZeroDivisionError", "message": "division by zero"}}
    ]


def test_protocol_rejects_an_impossible_case_selection() -> None:
    with pytest.raises(ValueError, match="selected_case_count"):
        evaluation_protocol(
            cases_route="/example/cases",
            steps=(),
            case_terminal="/example/case",
            run_terminal="/example/aggregate",
            selected_case_count=4,
            available_case_count=3,
        )


@pytest.mark.parametrize(
    ("benchmark", "expected_sha256"),
    (
        # OME-1527: DRACO, HealthBench and IFEval left this table when each became a local
        # inspect Task; their expressions are pinned by their published revisions and e2e
        # goldens. MedXpertQA, the last hand-built Benchmark, keeps the table from going empty
        # (an empty parametrize would skip this test silently).
        # Moved once (OME-1642): medxpert declares withhold, so its revision — in every route —
        # moved with it.
        # Moved again (spec 2026-10-20-url4-benchmark-expression, owner-approved): the
        # expression was rebuilt to URL4 Parts A–C; the revision did NOT move (pinned below).
        (MEDXPERT, "5fa018ad8dde9a251c94c93918acf60eed214d6f2832770a111900b0f59d443e"),
    ),
)
def test_canonical_benchmark_url4_is_pinned_byte_for_byte(
    benchmark: Benchmark, expected_sha256: str
) -> None:
    url4 = render(benchmark.build(benchmark.case_count))

    assert hashlib.sha256(url4.encode()).hexdigest() == expected_sha256


def test_the_rebuilt_expression_keeps_the_medxpert_revision() -> None:
    # INVARIANT (D5): the leaderboard keys on the revision; the rebuild must not move it.
    assert MEDXPERT.revision == "1e5a3b8a461a52f7"


def test_canonical_medxpert_binds_the_exact_selected_count_for_aggregation() -> None:
    # MedXpertQA stands in since IFEval, the original subject, became a local Task (OME-1527).
    # WHY a source, not an intent (spec R7): the count is an argument of the run terminal.
    rendered = render(MEDXPERT.build(2))

    assert "selected:0.0:'2'" in rendered
    assert "iteration.slice=0:2" in rendered


@pytest.mark.asyncio
async def test_a_top_level_source_resolves_inside_every_case_body() -> None:
    """A source added to the run's top-level group reaches every Case (how `$candidate` does)."""

    node = _protocol_node("benchmark-bindings")
    install_cases(node, "/example/cases", lambda: json.dumps([{"id": 1, "input": "case"}]))

    @node.endpoint("/example/evaluate-case")
    def evaluate_case(request: Request) -> str:
        return request.context

    @node.code("/example/case")
    def case(call: CodeCall) -> str:
        value = call.input("evaluated").value
        assert isinstance(value, str)
        return value

    @node.code("/example/aggregate")
    def aggregate(call: CodeCall) -> str:
        return json.dumps(_collected(call, "evaluations"))

    protocol = evaluation_protocol(
        cases_route="/example/cases",
        steps=(
            src(
                RelExpr(path="/example/evaluate-case", context="$shared", intent=Text("x")),
                name="evaluated",
                weight=0.0,
            ),
        ),
        case_terminal="/example/case",
        run_terminal="/example/aggregate",
        selected_case_count=1,
        available_case_count=1,
    )
    shared = src(Text("resolved-once"), name="shared", weight=0.0)
    bound = replace(protocol, sources=(shared, *protocol.sources))

    assert json.loads((await node.evaluate(render(bound))).text) == ["resolved-once"]
