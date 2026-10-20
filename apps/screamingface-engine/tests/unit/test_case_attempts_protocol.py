"""OME-1458 — the per-Case expression asks the Candidate once per Attempt.

FEATURE: `attempt_steps(attempts=N)` asks the Candidate N times as body sources
`attempt_1..attempt_N`; Attempt i's Candidate Invocation carries `attempt=i` for i ≥ 2, and the
case-evaluation code joins the N envelopes into one Attempts row the marking room folds.

STORY (spec acceptance 2): a two-Attempt Case, "What is 6 times 7?", with a stand-in Candidate
that answers 41 on Attempt 1 and 42 on Attempt 2. The Case Result carries both Attempts, shows
42 and scores 1.0.

INVARIANT: at one Attempt no Candidate Invocation names an Attempt, so Attempt 1's model calls
keep their cache identity.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from test_attempt_fold import _aggregate

from screamingface_engine.benchmarks.case_evaluation import case_evaluation_code
from screamingface_engine.benchmarks.case_selection import install_cases
from screamingface_engine.benchmarks.contract import CANDIDATE_ROUTE, encode_candidate_invocation
from screamingface_engine.benchmarks.definition import candidate_invocation
from screamingface_engine.benchmarks.graded_answer import (
    CASE_ATTEMPTS_SCHEMA,
    GRADED_ANSWER_SCHEMA,
)
from screamingface_engine.benchmarks.grading_endpoints import candidate_answer
from screamingface_engine.benchmarks.protocol import attempt_steps, evaluation_protocol
from url4 import CodeCall, Node, render
from url4.peer.server import Request, Url4Node


class _Candidate:
    """A stand-in Candidate: answers 41 on Attempt 1, 42 on Attempt 2, and records each call.

    It simulates only the Engine's Candidate route seeing the `attempt` param; no model, Recipe
    or gateway runs here (`test_attempt_egress.py` pins what the model calls send).
    """

    def __init__(self) -> None:
        self.attempts: list[str | None] = []

    def __call__(self, request: Request) -> str:
        attempt: str | None = request.params.get("attempt")
        self.attempts.append(attempt)
        return encode_candidate_invocation("42" if attempt == "2" else "41", "stop", None)


def _grade(case_id: int, invocation: str, _others: object) -> dict[str, Any]:
    """A stand-in check: records the Candidate's answer for the marking room."""

    answer = candidate_answer(invocation)
    return {
        "case": {
            "case_id": case_id,
            "status": "completed",
            "output": answer.text,
            "finish_reason": "stop",
            "refusal": None,
            "execution": None,
            "metadata": {},
        }
    }


def _node(candidate: _Candidate) -> Url4Node:
    node = Url4Node("attempts-protocol")
    node.endpoint(CANDIDATE_ROUTE)(candidate)
    install_cases(
        node,
        "/cases",
        lambda: json.dumps([{"id": 1, "case_id": "1", "input": "What is 6 times 7?"}]),
    )
    # WHY the one record as the grade: the stand-in check already writes the marking room's row.
    node.code("/case-evaluation")(
        case_evaluation_code(
            label="Attempts probe",
            check=_grade,
            build_case_grade=lambda _case_id, records: records[0],
            observe_grading=False,
        )
    )

    @node.code("/aggregate")
    def aggregate(call: CodeCall) -> str:
        rows = call.input("evaluations").value
        assert isinstance(rows, list)
        return json.dumps(rows[0])

    return node


def _case(attempts: int) -> Node:
    return evaluation_protocol(
        cases_route="/cases",
        steps=attempt_steps("$item.input", attempts=attempts, case_count=1, web_search=False),
        case_terminal="/case-evaluation",
        run_terminal="/aggregate",
        selected_case_count=1,
        available_case_count=1,
    )


async def _run(candidate: _Candidate, attempts: int) -> dict[str, Any]:
    result = await _node(candidate).evaluate(render(_case(attempts)), env={"candidate": "recipe"})
    return json.loads(result.text)


def test_one_attempt_renders_byte_identical() -> None:
    # INVARIANT: the default and an explicit 1 are the same text, and neither names Attempts.
    default = candidate_invocation("$item.input", web_search=False, case_count=1)

    assert render(
        candidate_invocation("$item.input", web_search=False, case_count=1, attempt=1)
    ) == (render(default))
    assert "attempt=" not in render(_case(1))
    assert "attempt_2" not in render(_case(1))


def test_every_attempt_is_built_with_its_own_number() -> None:
    # INVARIANT: Attempt i ≥ 2 carries its number on its Candidate Invocation, or it leaves the
    # Engine identical to Attempt 1 and an unseeded run is served Attempt 1's stored reply.
    # WHY no rewrite to refuse any more: `attempt_steps` builds each Attempt's Candidate
    # Invocation with its number, so no Candidate Invocation can sit out of the rewrite's reach.
    rendered: str = render(_case(3))

    assert rendered.count("attempt=2") == 1
    assert rendered.count("attempt=3") == 1
    assert "attempt=1" not in rendered
    with pytest.raises(ValueError, match="attempt"):
        candidate_invocation("$item.input", web_search=False, case_count=1, attempt=0)


def test_attempt_two_carries_the_attempt_param_and_one_does_not() -> None:
    rendered: str = render(_case(2))

    assert rendered.count("attempt=2") == 1
    assert "attempt=1" not in rendered
    # WHY: the Attempts are named body sources; the case-evaluation code joins them.
    assert "attempt_2:0.0:" in rendered


@pytest.mark.asyncio
async def test_two_attempts_invoke_the_candidate_twice() -> None:
    candidate = _Candidate()

    result: dict[str, Any] = await _run(candidate, 2)

    # The Attempts are siblings in one expression, so they may run side by side; each is
    # asked exactly once, and the joined row keeps them in Attempt order.
    assert len(candidate.attempts) == 2
    assert set(candidate.attempts) == {None, "2"}
    assert result["schema"] == CASE_ATTEMPTS_SCHEMA
    assert result["case_id"] == "1"
    assert [row["schema"] for row in result["attempts"]] == [GRADED_ANSWER_SCHEMA] * 2


def test_an_attempts_case_scores_the_any_match_number_end_to_end() -> None:
    # Spec acceptance 2: replies 41 then 42 → both Attempts kept, 42 shown, the Case 1.0.
    row: dict[str, Any] = asyncio.run(_run(_Candidate(), 2))

    result: dict[str, Any] = _aggregate(row["attempts"], ["42"])

    case: dict[str, Any] = result["cases"][0]
    assert result["score"] == 1.0
    assert case["output"] == "42"
    assert [attempt["output"] for attempt in case["attempts"]] == ["41", "42"]


def test_attempts_below_one_are_refused() -> None:
    with pytest.raises(ValueError, match="attempts"):
        _case(0)
