"""OME-1458 — the per-Case expression asks the Candidate once per Attempt.

FEATURE: `preserve_candidate_outcome(attempts=N)` runs the one-Attempt execution N times;
Attempt i's Candidate Invocation carries `attempt=i` for i ≥ 2, and the N envelopes are joined
into one Attempts row the marking room folds.

STORY (spec acceptance 2): a two-Attempt Case, "What is 6 times 7?", with a stand-in Candidate
that answers 41 on Attempt 1 and 42 on Attempt 2. The Case Result carries both Attempts, shows
42 and scores 1.0.

INVARIANT: at one Attempt the expression is exactly today's, so no published Benchmark's URL4
moves (the pinned hashes in `test_benchmark_protocol.py` stay green, unmodified).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from test_attempt_fold import _aggregate

from screamingface_engine.benchmarks.contract import CANDIDATE_ROUTE, encode_candidate_invocation
from screamingface_engine.benchmarks.graded_answer import (
    CASE_ATTEMPTS_SCHEMA,
    GRADED_ANSWER_SCHEMA,
    install_graded_answer_endpoint,
)
from screamingface_engine.benchmarks.grading_endpoints import candidate_answer
from screamingface_engine.benchmarks.protocol import preserve_candidate_outcome
from url4 import RelExpr, Text, render
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


def _grade(request: Request) -> str:
    """A stand-in grading step: records the Candidate's answer for the marking room."""

    answer = candidate_answer(request.context)
    return json.dumps(
        {
            "case": {
                "case_id": 1,
                "status": "completed",
                "output": answer.text,
                "finish_reason": "stop",
                "refusal": None,
                "execution": None,
                "metadata": {},
            }
        }
    )


def _node(candidate: _Candidate) -> Url4Node:
    node = Url4Node("attempts-protocol")
    node.endpoint(CANDIDATE_ROUTE)(candidate)
    node.endpoint("/grade")(_grade)
    install_graded_answer_endpoint(node)
    return node


def _case(attempts: int) -> Any:
    return preserve_candidate_outcome(
        candidate_invocation=RelExpr(
            path=CANDIDATE_ROUTE,
            context="What is 6 times 7?",
            intent=Text("$candidate"),
            params=(("web_search", "false"),),
        ),
        grading=RelExpr(path="/grade", context="$candidate_invocation", intent=Text("")),
        case_id="1",
        attempts=attempts,
    )


def test_one_attempt_renders_byte_identical() -> None:
    # INVARIANT: the default and an explicit 1 are the same text, and neither names Attempts.
    default = preserve_candidate_outcome(
        candidate_invocation=RelExpr(path=CANDIDATE_ROUTE, context="q", intent=Text("")),
        grading=RelExpr(path="/grade", context="$candidate_invocation", intent=Text("")),
        case_id="1",
    )

    assert render(_case(1)) == render(_case(1))
    assert "attempt" not in render(default)
    assert "case-attempts" not in render(_case(1))


def test_attempt_two_carries_the_attempt_param_and_one_does_not() -> None:
    rendered: str = render(_case(2))

    assert rendered.count("attempt=2") == 1
    assert "attempt=1" not in rendered
    assert "/benchmarks/case-attempts" in rendered


@pytest.mark.asyncio
async def test_two_attempts_invoke_the_candidate_twice() -> None:
    candidate = _Candidate()

    result: dict[str, Any] = json.loads((await _node(candidate).evaluate(render(_case(2)))).text)

    # The Attempts are siblings in one expression, so they may run side by side; each is
    # asked exactly once, and the joined row keeps them in Attempt order.
    assert len(candidate.attempts) == 2
    assert set(candidate.attempts) == {None, "2"}
    assert result["schema"] == CASE_ATTEMPTS_SCHEMA
    assert result["case_id"] == "1"
    assert [row["schema"] for row in result["attempts"]] == [GRADED_ANSWER_SCHEMA] * 2


def test_an_attempts_case_scores_the_any_match_number_end_to_end() -> None:
    # Spec acceptance 2: replies 41 then 42 → both Attempts kept, 42 shown, the Case 1.0.
    evaluated = asyncio.run(_node(_Candidate()).evaluate(render(_case(2))))
    row: dict[str, Any] = json.loads(evaluated.text)

    result: dict[str, Any] = _aggregate(row["attempts"], ["42"])

    case: dict[str, Any] = result["cases"][0]
    assert result["score"] == 1.0
    assert case["output"] == "42"
    assert [attempt["output"] for attempt in case["attempts"]] == ["41", "42"]


def test_attempts_below_one_are_refused() -> None:
    with pytest.raises(ValueError, match="attempts"):
        _case(0)
