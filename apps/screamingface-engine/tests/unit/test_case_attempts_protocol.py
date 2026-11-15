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
from test_attempt_fold import _aggregate, _aggregate_mean

from screamingface_engine.benchmarks.contract import CANDIDATE_ROUTE, encode_candidate_invocation
from screamingface_engine.benchmarks.definition import candidate
from screamingface_engine.benchmarks.graded_answer import (
    CASE_ATTEMPTS_SCHEMA,
    GRADED_ANSWER_SCHEMA,
    install_graded_answer_endpoint,
)
from screamingface_engine.benchmarks.grading_endpoints import candidate_answer
from screamingface_engine.benchmarks.protocol import preserve_candidate_outcome
from url4 import RelExpr, Text, iterate, render, src, struct
from url4.core.errors import ResolutionError
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


_CANDIDATE_INVOCATION = RelExpr(
    path=CANDIDATE_ROUTE,
    context="What is 6 times 7?",
    intent=Text("$candidate"),
    params=(("web_search", "false"),),
)
_GRADING = RelExpr(path="/grade", context="$candidate_invocation", intent=Text(""))


def _case(attempts: int) -> Any:
    return preserve_candidate_outcome(
        candidate_invocation=_CANDIDATE_INVOCATION,
        grading=_GRADING,
        case_id="1",
        attempts=attempts,
    )


def test_one_attempt_renders_byte_identical() -> None:
    # INVARIANT: the default and an explicit 1 are the same text, and neither names Attempts.
    default = preserve_candidate_outcome(
        candidate_invocation=_CANDIDATE_INVOCATION, grading=_GRADING, case_id="1"
    )

    assert render(_case(1)) == render(default)
    assert "attempt" not in render(default)
    assert "case-attempts" not in render(default)


def test_a_candidate_invocation_the_rewrite_cannot_reach_is_refused_at_build() -> None:
    # INVARIANT: Attempt 2 must carry its number, or it leaves the Engine identical to
    # Attempt 1 and an unseeded run is served Attempt 1's stored reply. Stand-in: the Candidate
    # Invocation nested inside an `iterate`, a node kind the rewrite does not walk.
    hidden = iterate(
        [struct({"question": "What is 6 times 7?"})],
        body=(src(_CANDIDATE_INVOCATION, name="answer", weight=0.0),),
        intent=Text("$answer"),
    )

    with pytest.raises(ValueError, match="Attempt 2 reached no Candidate Invocation"):
        preserve_candidate_outcome(
            candidate_invocation=hidden, grading=_GRADING, case_id="1", attempts=2
        )
    # One Attempt carries no number, so the same node still builds.
    preserve_candidate_outcome(candidate_invocation=hidden, grading=_GRADING, case_id="1")


def test_an_unreachable_candidate_invocation_beside_a_reachable_one_is_refused() -> None:
    # INVARIANT: every Candidate Invocation in Attempt 2 carries its number, not just one.
    # Stand-in: a reasoning turn nested inside an `iterate` binding (a node kind the rewrite
    # does not walk) beside a reachable final Candidate Invocation, the MedXpertQA shape. The
    # final call would be numbered, but the reasoning call would keep Attempt 1's cache identity,
    # so Attempt 2 would reuse Attempt 1's reasoning answer.
    reasoning = iterate(
        [struct({"question": "What is 6 times 7?"})],
        body=(src(_CANDIDATE_INVOCATION, name="answer", weight=0.0),),
        intent=Text("$answer"),
    )
    bindings = (src(reasoning, name="reasoning", weight=0.0),)

    with pytest.raises(ValueError, match="Attempt 2 numbered 1 of 2 Candidate Invocations"):
        preserve_candidate_outcome(
            candidate_invocation=_CANDIDATE_INVOCATION,
            grading=_GRADING,
            case_id="1",
            bindings=bindings,
            attempts=2,
        )
    # One Attempt carries no number, so the same nodes still build.
    preserve_candidate_outcome(
        candidate_invocation=_CANDIDATE_INVOCATION,
        grading=_GRADING,
        case_id="1",
        bindings=bindings,
    )


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


# --- a failed Candidate call fails only its own Attempt (2026-11-10 amendment) ---------------
#
# FEATURE (docs/spec/2026-11-10-attempt-call-collect.md): each Attempt's execution runs inside
# its own collecting iterate, so an errored call becomes that Attempt's row (an error payload
# carrying the code) and the Attempts that answered are kept. Before this, the error raised out
# of the whole Case and 4 right tries + 1 token cap scored 0.0 (OME-1458's accepted limitation).


class _FailingCandidate:
    """A stand-in Candidate that answers 42 except on the named Attempts, where its call errors
    by ``code`` — the shape a spent token budget or a gateway failure takes at the url4 node.
    No model, Recipe or gateway runs here."""

    def __init__(self, code: str, failing: set[str | None]) -> None:
        self.code = code
        self.failing = failing
        self.attempts: list[str | None] = []

    def __call__(self, request: Request) -> str:
        attempt: str | None = request.params.get("attempt")
        self.attempts.append(attempt)
        if attempt in self.failing:
            raise ResolutionError(f"stand-in {self.code}", code=self.code, permanent=True)
        return encode_candidate_invocation("42", "stop", None)


def _failing_node(candidate: _FailingCandidate) -> Url4Node:
    node = Url4Node("attempts-protocol-failing")
    node.endpoint(CANDIDATE_ROUTE)(candidate)
    node.endpoint("/grade")(_grade)
    install_graded_answer_endpoint(node)
    return node


def _evaluated_attempts(candidate: _FailingCandidate, attempts: int) -> list[Any]:
    evaluated = asyncio.run(_failing_node(candidate).evaluate(render(_case(attempts))))
    row: dict[str, Any] = json.loads(evaluated.text)
    assert row["schema"] == CASE_ATTEMPTS_SCHEMA
    return row["attempts"]


def test_a_failed_call_in_one_attempt_keeps_the_others() -> None:
    # STORY: three Attempts, the second runs out of tokens before any text. Attempts 1 and 3
    # answer 42 and are kept; Attempt 2 arrives as an error row carrying model_token_cap.
    candidate = _FailingCandidate("model_token_cap", {"2"})

    rows: list[Any] = _evaluated_attempts(candidate, 3)

    assert len(candidate.attempts) == 3
    assert [row.get("schema") for row in rows] == [GRADED_ANSWER_SCHEMA, None, GRADED_ANSWER_SCHEMA]
    assert rows[1]["error"]["code"] == "model_token_cap"


@pytest.mark.parametrize(
    ("code", "mean_score"),
    [("model_token_cap", round(2 / 3, 4)), ("gateway_internal_error", 1.0)],
)
def test_the_marking_room_files_the_errored_attempt_by_its_code(
    code: str, mean_score: float
) -> None:
    # INVARIANT (spec D3, D4): the failed Attempt carries the error's own code, so the fold can
    # tell an empty answer (a wrong try: 2 right of 3) from a gateway error (no try: 2 of 2).
    rows: list[Any] = _evaluated_attempts(_FailingCandidate(code, {"2"}), 3)

    folded_any: dict[str, Any] = _aggregate(rows, ["42"])["cases"][0]
    folded_mean: dict[str, Any] = _aggregate_mean(rows, ["42"])["cases"][0]

    for case in (folded_any, folded_mean):
        assert case["status"] == "scored"
        assert [attempt["status"] for attempt in case["attempts"]] == ["scored", "failed", "scored"]
        assert case["attempts"][1]["failures"][0]["code"] == code
        assert case["output"] == "42"
    assert folded_any["grade"]["score"] == 1.0
    assert folded_mean["grade"]["score"] == mean_score


def test_every_call_failing_is_a_failed_case_led_by_attempt_one() -> None:
    rows: list[Any] = _evaluated_attempts(_FailingCandidate("model_token_cap", {None, "2"}), 2)

    case: dict[str, Any] = _aggregate_mean(rows, ["42"])["cases"][0]

    assert case["status"] == "failed"
    assert case["failures"][0]["code"] == "model_token_cap"
    assert [attempt["status"] for attempt in case["attempts"]] == ["failed", "failed"]


def test_the_candidate_still_sees_its_case_position_inside_every_attempt() -> None:
    # WHY (spec D2): inside the per-Attempt iterate url4's $index is the row's own index, 0;
    # the Case's position is bound once at Case level and read inside, so the Candidate is
    # still told "Case k of N" (progress reads it too). Two Cases, two Attempts each.
    seen: list[dict[str, Any]] = []

    def positioned(request: Request) -> str:
        seen.append(json.loads(request.context))
        return encode_candidate_invocation("42", "stop", None)

    node = Url4Node("attempts-position")
    node.endpoint(CANDIDATE_ROUTE)(positioned)
    node.endpoint("/grade")(_grade)
    install_graded_answer_endpoint(node)
    invocation = candidate(
        "$item.input", web_search=False, case_id="$item.id", case_index="$index", case_count="2"
    )
    case = preserve_candidate_outcome(
        candidate_invocation=invocation, grading=_GRADING, case_id="$item.id", attempts=2
    )
    cases = iterate(
        [struct({"id": "1", "input": "q1"}), struct({"id": "2", "input": "q2"})],
        body=(src(case, name="case", weight=0.0),),
        intent=Text("$case"),
        on_error="collect",
    )

    asyncio.run(node.evaluate(render(cases)))

    assert sorted((s["case_id"], s["case_index"]) for s in seen) == [
        ("1", "0"),
        ("1", "0"),
        ("2", "1"),
        ("2", "1"),
    ]
