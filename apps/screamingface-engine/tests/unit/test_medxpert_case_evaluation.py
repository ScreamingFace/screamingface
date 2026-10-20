"""MedXpertQA per-Case envelopes and the case-evaluation code that packs them."""

from __future__ import annotations

import json
from typing import Any

import pytest

from screamingface_engine.benchmarks.case_evaluation import case_evaluation_code
from screamingface_engine.benchmarks.case_selection import install_cases
from screamingface_engine.benchmarks.code_calls import (
    first_grading,
    run_case_evaluation,
    run_code,
)
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.graded_answer import CASE_ATTEMPTS_SCHEMA
from screamingface_engine.benchmarks.medxpert.case_grade import (
    CASE_GRADE_SCHEMA,
    CHECK_SCHEMA,
    build_case_grade,
    decode_case_grade,
)
from screamingface_engine.benchmarks.protocol import attempt_steps, evaluation_protocol
from url4 import CodeCall, render
from url4.core.errors import ResolutionError, Url4Error
from url4.peer.server import Request, Url4Node


def _check_record(case_id: int = 1, letter: str = "C") -> dict[str, object]:
    return {"schema": CHECK_SCHEMA, "case_id": case_id, "answer": letter}


_CASE = {"id": 1, "case_id": "1"}


def _node(record_case_id: int = 1) -> Url4Node:
    """A node with MedXpertQA's case-evaluation code; the stand-in check reads the answer text.

    WHY the code mount (spec §3.2): the retired `attempt_records_endpoint` route is now the
    case-evaluation code, which runs the check and the Case grade per Attempt in process.
    """

    def check(_case_id: int, invocation: str, _others: object) -> dict[str, object]:
        letter = json.loads(invocation)["output"]
        return _check_record(case_id=record_case_id, letter=letter)

    node = Url4Node("medxpert-case-evaluation")
    node.code("/case-evaluation")(
        case_evaluation_code(
            label="MedXpertQA Case evaluation",
            check=check,
            build_case_grade=build_case_grade,
            observe_grading=True,
        )
    )
    return node


def _answer(letter: str) -> str:
    return encode_candidate_invocation(letter, "stop", None)


async def _evaluate(node: Url4Node, *letters: str) -> Any:
    return json.loads(
        await run_case_evaluation(
            node, "/case-evaluation", case=_CASE, attempts=[_answer(letter) for letter in letters]
        )
    )


@pytest.mark.asyncio
async def test_route_accepts_the_attempt_struct_the_expression_renders() -> None:
    """REGRESSION: one Attempt yields one Case grade over exactly that Attempt's record."""

    row = await _evaluate(_node(), "C")

    assert row["grading"] == [
        {
            "schema": CASE_GRADE_SCHEMA,
            "case_id": 1,
            "attempts": [_check_record()],
        }
    ]


@pytest.mark.asyncio
async def test_route_packs_consecutive_attempts_in_order() -> None:
    # WHY one envelope per Attempt (spec §3.3): each Attempt is graded on its own, and the
    # row joins them in Attempt order as `case-attempts.v1`.
    row = await _evaluate(_node(), "A", "B")

    assert row["schema"] == CASE_ATTEMPTS_SCHEMA
    assert [attempt["grading"][0]["attempts"][0]["answer"] for attempt in row["attempts"]] == [
        "A",
        "B",
    ]


@pytest.mark.asyncio
async def test_route_rejects_a_gap_in_the_attempt_numbering() -> None:
    # WHY Url4Error: a failing code call surfaces as url4's intent_error (Spec C §13.6); the
    # Engine's own message is kept in it.
    sources = {"case": json.dumps(_CASE), "attempt_1": _answer("C"), "attempt_3": _answer("D")}

    with pytest.raises(Url4Error, match="consecutive attempt_1..attempt_N"):
        await run_code(_node(), "/case-evaluation", sources)


@pytest.mark.asyncio
async def test_route_reraises_an_upstream_collected_failure() -> None:
    """A failed Candidate fails its Case with the ORIGINAL cause, before any grading runs.

    WHY changed (spec §3.3): the Attempt is a required source of the case-evaluation code, so
    an upstream failure never reaches it; the iteration collects the original error instead.
    """

    node = _node()
    install_cases(node, "/cases", lambda: json.dumps([{"id": 1, "case_id": "1", "input": "q"}]))
    graded: list[object] = []

    @node.endpoint("/benchmarks/candidate")
    def candidate(_request: Request) -> str:
        raise ResolutionError(
            "candidate call ran out of tokens", code="candidate_failed", permanent=True
        )

    @node.code("/aggregate")
    def aggregate(call: CodeCall) -> str:
        graded.append(call.input("evaluations").value)
        return "done"

    protocol = evaluation_protocol(
        cases_route="/cases",
        steps=attempt_steps("$item.input", attempts=1, case_count=1, web_search=False),
        case_terminal="/case-evaluation",
        run_terminal="/aggregate",
        selected_case_count=1,
        available_case_count=1,
    )

    await node.evaluate(render(protocol), env={"candidate": "recipe"})

    [rows] = graded
    assert isinstance(rows, list)
    assert rows[0]["error"]["message"] == "candidate call ran out of tokens"
    assert rows[0]["error"]["code"] == "candidate_failed"


@pytest.mark.asyncio
async def test_route_reports_the_context_head_on_a_bind_level_failure() -> None:
    # WHY no context head (spec §3.3): a bind-level failure is now that Attempt's grading
    # outcome, beside the Candidate answer, and keeps its contract-error code.
    row = await _evaluate(_node(record_case_id=2), "C")

    error = first_grading(json.dumps(row))["error"]
    assert error["code"] == "benchmark_contract_error"
    assert "belongs to another Case" in error["message"]
    assert row["candidate_invocation"] == _answer("C")


@pytest.mark.asyncio
async def test_route_rejects_a_context_that_is_not_json() -> None:
    """A Case row that is not JSON fails the call before any check runs."""

    with pytest.raises(Url4Error, match="must be JSON: "):
        await run_code(
            _node(), "/case-evaluation", {"case": "not json at all", "attempt_1": _answer("C")}
        )


def test_bind_rejects_an_attempt_from_another_case() -> None:
    with pytest.raises(ValueError, match="belongs to another Case"):
        build_case_grade(1, [_check_record(case_id=2)])


def test_bind_rejects_an_attempt_without_the_check_schema() -> None:
    with pytest.raises(ValueError, match=f"must carry schema {CHECK_SCHEMA}"):
        build_case_grade(1, [{"case_id": 1, "answer": "C"}])


def test_bind_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="at least one attempt"):
        build_case_grade(1, [])


def test_decode_round_trips_what_bind_produced() -> None:
    bound = build_case_grade(1, [_check_record()])

    assert decode_case_grade(bound, 1) == bound


def test_decode_rejects_unknown_fields() -> None:
    bound = build_case_grade(1, [_check_record()]) | {"score": 1.0}

    with pytest.raises(ValueError, match=r"unknown fields \['score'\]"):
        decode_case_grade(bound, 1)


def test_decode_rejects_an_envelope_for_another_case() -> None:
    bound = build_case_grade(1, [_check_record()])

    with pytest.raises(ValueError, match="belongs to another Case"):
        decode_case_grade(bound, 2)
