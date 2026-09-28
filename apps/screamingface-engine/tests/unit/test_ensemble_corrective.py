"""The generic corrective-loop substrate and its invocation boundaries.

FEATURE: benchmark-independent corrective loop (OME-796 / OME-827).
STORY: as a client, a compiled `sf.CorrectiveLoop` candidate drives its rounds
through benchmark-neutral endpoints against ANY benchmark that
advertises a check surface — no benchmark-specific loop code anywhere.

The check-surface port record replaces both the old "PASSED" feedback sentinel
(structured `passed` bool) and the IFEval-private `_strict_satisfaction` call
(each benchmark computes `satisfaction` behind its adapter; the gate/select
just read the number). The tests here pin, in order: (1) the engine semantics
the design rests on — an empty gate collection means the gated body NEVER
executes; (2) each endpoint's decision table; (3) the port
record contract itself.
"""

from __future__ import annotations

import json

import pytest

from screamingface_engine.benchmarks.contract import (
    decode_candidate_invocation,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.ensemble.policy import (
    ANSWER_ROUTE,
    CHECK_SURFACE_SCHEMA,
    GATE_ROUTE,
    MEMBER_LABEL_SCHEME,
    SELECT_ROUTE,
)
from screamingface_engine.world.corrective import install_corrective_runtime
from url4 import RelExpr, Text, expr, iterate, ref, render, src, text
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node


def _node() -> Url4Node:
    node = Url4Node("test")
    install_corrective_runtime(node)
    return node


def _record(
    *,
    passed: bool,
    satisfaction: float,
    feedback: str = "",
    answer: str = "an answer",
) -> dict[str, object]:
    invocation = encode_candidate_invocation(answer, "stop", None)
    return {
        "schema": CHECK_SURFACE_SCHEMA,
        "passed": passed,
        "satisfaction": satisfaction,
        "feedback": feedback,
        "answer": answer,
        "invocation": invocation,
    }


def _answer(invocation: str) -> str:
    outcome = json.loads(invocation)
    output, _finish_reason, refusal = decode_candidate_invocation(outcome["invocation"])
    assert refusal is None
    return output


def _outcome(answer: str, *, round: int = 1, passed: bool = True) -> dict[str, object]:
    return {
        "schema": "screamingface.corrective-outcome.v1",
        "invocation": encode_candidate_invocation(answer, "stop", None),
        "round": round,
        "passed": passed,
    }


_PASS = _record(passed=True, satisfaction=1.0, answer="passing answer")
_HALF = _record(passed=False, satisfaction=0.5, feedback="half the requirements failed")
_FAIL = _record(passed=False, satisfaction=0.0, feedback="every requirement failed")


async def _call(node: Url4Node, path: str, payload: object, intent: str) -> str:
    result = await node.evaluate(
        render(
            expr(
                src(
                    text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
                    name="payload",
                    weight=0.0,
                ),
                RelExpr(path=path, context="$payload", intent=Text(intent)),
                intent=Text(""),
            )
        )
    )
    return result.text


# --- (1) the engine semantics the whole design rests on ---------------------------


def _probe_expression(round_records: dict[str, dict[str, object]]) -> str:
    """A production-shaped body: gate + gated iterate as SIBLINGS — the shape the
    client compiler emits for every round after the first."""

    body = expr(
        src(
            text(json.dumps(round_records, separators=(",", ":"))),
            name="round",
            weight=0.0,
        ),
        src(
            RelExpr(path=GATE_ROUTE, context="$round", intent=Text("continue:1:3")),
            name="gate",
            weight=0.0,
        ),
        src(
            iterate(
                ref("gate"),
                body=(
                    src(
                        RelExpr(path="/probe", context="$item", intent=Text("ran")),
                        name="probed",
                        weight=0.0,
                    ),
                ),
                intent=Text("$probed"),
            ),
            name="outcome",
            weight=0.0,
        ),
        intent=Text("$outcome"),
    )
    return render(expr(src(body, name="checked", weight=0.0), intent=Text("$checked")))


@pytest.mark.asyncio
async def test_an_empty_gate_collection_skips_the_iterate_body_entirely() -> None:
    # INVARIANT: iterate over a gate that returned [] executes its body ZERO times —
    # this is what makes a round-1 pass cost N member calls and nothing else. If this
    # ever breaks, the corrective loop silently degenerates into an unconditional
    # retry loop and `max_rounds` stops being a cost cap.
    probes: list[str] = []
    node = _node()

    @node.endpoint("/probe")
    def probe(request) -> str:
        probes.append(request.intent)
        return json.dumps({"probed": True})

    result = await node.evaluate(_probe_expression({"a": _PASS, "b": _FAIL}))
    assert probes == []
    assert json.loads(result.text) == []


@pytest.mark.asyncio
async def test_a_no_pass_round_runs_the_gated_body_exactly_once() -> None:
    probes: list[str] = []
    node = _node()

    @node.endpoint("/probe")
    def probe(request) -> str:
        probes.append(request.intent)
        return json.dumps({"probed": True})

    result = await node.evaluate(_probe_expression({"a": _FAIL, "b": _HALF}))
    assert probes == ["ran"]
    assert json.loads(result.text) == [{"probed": True}]


# --- (2) the gate decision table --------------------------------------------------


@pytest.mark.asyncio
async def test_continue_gate_stops_on_any_passer() -> None:
    node = _node()
    reply = await _call(node, GATE_ROUTE, {"a": _PASS, "b": _FAIL}, "continue:1:3")
    assert json.loads(reply) == []


@pytest.mark.asyncio
async def test_continue_gate_proceeds_when_nobody_passed() -> None:
    node = _node()
    reply = await _call(node, GATE_ROUTE, {"a": _FAIL, "b": _HALF}, "continue:1:3")
    assert json.loads(reply) == [{"attempt": 2}]


@pytest.mark.asyncio
async def test_continue_gate_never_exceeds_the_round_budget() -> None:
    # WHY: max_rounds is a COST CAP the engine enforces too — even a hand-written
    # expression cannot buy a round past the budget its own intent declares.
    node = _node()
    reply = await _call(node, GATE_ROUTE, {"a": _FAIL, "b": _FAIL}, "continue:3:3")
    assert json.loads(reply) == []


@pytest.mark.asyncio
async def test_continue_gate_supports_a_single_member_for_self_correction() -> None:
    # SelfCorrective drives the same gate with a one-entry round: the structural
    # >=2 member floor is a PANEL rule enforced at recipe construction, not here.
    node = _node()
    reply = await _call(node, GATE_ROUTE, {"a": _FAIL}, "continue:1:3")
    assert json.loads(reply) == [{"attempt": 2}]


@pytest.mark.asyncio
async def test_tie_gate_is_empty_for_a_single_passer() -> None:
    # A lone passer needs NO judge call — the cheapest and commonest path.
    node = _node()
    reply = await _call(node, GATE_ROUTE, {"a": _PASS, "b": _FAIL}, "tie:1:3")
    assert json.loads(reply) == []


@pytest.mark.asyncio
async def test_tie_gate_names_the_passers_when_two_pass() -> None:
    node = _node()
    other = _record(passed=True, satisfaction=1.0, answer="another passing answer")
    reply = await _call(node, GATE_ROUTE, {"a": _PASS, "b": other}, "tie:1:3")
    (payload,) = json.loads(reply)
    assert payload["attempt"] == 1
    assert [candidate["key"] for candidate in payload["candidates"]] == ["A", "B"]
    assert [candidate["answer"] for candidate in payload["candidates"]] == [
        "passing answer",
        "another passing answer",
    ]


@pytest.mark.asyncio
async def test_tie_gate_is_empty_for_a_no_pass_round_before_the_final_attempt() -> None:
    # A no-pass round before the budget is spent retries instead of judging.
    node = _node()
    reply = await _call(node, GATE_ROUTE, {"a": _FAIL, "b": _HALF}, "tie:1:3")
    assert json.loads(reply) == []


@pytest.mark.asyncio
async def test_tie_gate_ties_never_passing_members_on_equal_satisfaction() -> None:
    # WHY satisfaction sits in the record: the old loop computed the never-pass
    # ranking with IFEval-private code; the port inverts it — the gate just reads
    # the number the benchmark's adapter computed.
    node = _node()
    twin = _record(passed=False, satisfaction=0.5, feedback="also half", answer="twin")
    reply = await _call(node, GATE_ROUTE, {"a": _HALF, "b": twin, "c": _FAIL}, "tie:3:3")
    (payload,) = json.loads(reply)
    assert [candidate["key"] for candidate in payload["candidates"]] == ["A", "B"]


@pytest.mark.asyncio
async def test_tie_gate_is_empty_for_a_unique_never_pass_best() -> None:
    node = _node()
    reply = await _call(node, GATE_ROUTE, {"a": _HALF, "b": _FAIL}, "tie:3:3")
    assert json.loads(reply) == []


@pytest.mark.asyncio
async def test_gate_rejects_an_unknown_intent() -> None:
    node = _node()
    with pytest.raises(ResolutionError, match="unsupported"):
        await _call(node, GATE_ROUTE, {"a": _PASS, "b": _FAIL}, "loop:1:3")


@pytest.mark.asyncio
async def test_gate_accepts_members_beyond_the_retired_lanl_ceiling() -> None:
    round_records = {letter: _record(passed=False, satisfaction=0.0) for letter in "abcde"}
    node = _node()
    reply = await _call(node, GATE_ROUTE, round_records, "continue:1:3")

    assert json.loads(reply) == [{"attempt": 2}]


@pytest.mark.asyncio
async def test_select_accepts_a_multi_character_member_label() -> None:
    labels = tuple(chr(ord("a") + index) for index in range(26)) + ("aa",)
    round_records = {
        label: _record(
            passed=label == "aa",
            satisfaction=1.0 if label == "aa" else 0.0,
            answer=f"answer {label}",
        )
        for label in labels
    }
    node = _node()

    reply = await _call(
        node,
        SELECT_ROUTE,
        {"round": round_records, "tie": []},
        "1",
    )

    assert _answer(reply) == "answer aa"


@pytest.mark.asyncio
async def test_gate_rejects_non_consecutive_member_letters() -> None:
    node = _node()
    with pytest.raises(ResolutionError, match="consecutive"):
        await _call(node, GATE_ROUTE, {"a": _FAIL, "c": _FAIL}, "continue:1:3")


# --- select: verbatim representative answer ---------------------------------------


@pytest.mark.asyncio
async def test_select_returns_the_lone_passer_verbatim() -> None:
    node = _node()
    reply = await _call(node, SELECT_ROUTE, {"round": {"a": _FAIL, "b": _PASS}, "tie": []}, "1")
    # INVARIANT: the returned text is always a member's exact answer — selection can
    # choose but never rewrite, so it cannot break a requirement a member satisfied.
    assert _answer(reply) == "passing answer"


@pytest.mark.asyncio
async def test_select_honors_the_judge_letter_between_passers() -> None:
    node = _node()
    other = _record(passed=True, satisfaction=1.0, answer="the b answer")
    reply = await _call(node, SELECT_ROUTE, {"round": {"a": _PASS, "b": other}, "tie": ["B"]}, "1")
    assert _answer(reply) == "the b answer"


@pytest.mark.asyncio
async def test_select_falls_back_to_the_first_passer_on_judge_prose() -> None:
    # Prose gets no vote: an unparseable judge reply must not fail the case.
    node = _node()
    other = _record(passed=True, satisfaction=1.0, answer="the b answer")
    reply = await _call(
        node,
        SELECT_ROUTE,
        {"round": {"a": _PASS, "b": other}, "tie": ["I choose the second one"]},
        "1",
    )
    assert _answer(reply) == "passing answer"


@pytest.mark.asyncio
async def test_select_accepts_a_punctuated_judge_letter() -> None:
    node = _node()
    other = _record(passed=True, satisfaction=1.0, answer="the b answer")
    reply = await _call(node, SELECT_ROUTE, {"round": {"a": _PASS, "b": other}, "tie": ["b."]}, "1")
    assert _answer(reply) == "the b answer"


@pytest.mark.asyncio
async def test_select_ignores_a_letter_outside_the_member_set() -> None:
    node = _node()
    other = _record(passed=True, satisfaction=1.0, answer="the b answer")
    reply = await _call(node, SELECT_ROUTE, {"round": {"a": _PASS, "b": other}, "tie": ["D"]}, "1")
    assert _answer(reply) == "passing answer"


@pytest.mark.asyncio
async def test_select_picks_the_maximal_satisfaction_answer_when_nobody_passed() -> None:
    node = _node()
    reply = await _call(node, SELECT_ROUTE, {"round": {"a": _FAIL, "b": _HALF}, "tie": []}, "3")
    assert _answer(reply) == _HALF["answer"]


@pytest.mark.asyncio
async def test_select_defers_an_exact_satisfaction_tie_to_the_judge() -> None:
    node = _node()
    twin = _record(passed=False, satisfaction=0.5, feedback="also half", answer="twin")
    reply = await _call(node, SELECT_ROUTE, {"round": {"a": _HALF, "b": twin}, "tie": ["B"]}, "3")
    assert _answer(reply) == "twin"


@pytest.mark.asyncio
async def test_select_breaks_a_tie_of_ties_deterministically() -> None:
    # Tie-of-tie -> first member: reproducibility beats sophistication.
    node = _node()
    twin = _record(passed=False, satisfaction=0.5, feedback="also half", answer="twin")
    reply = await _call(node, SELECT_ROUTE, {"round": {"a": _HALF, "b": twin}, "tie": []}, "3")
    assert _answer(reply) == _HALF["answer"]


@pytest.mark.asyncio
async def test_select_requires_exactly_round_and_tie() -> None:
    node = _node()
    with pytest.raises(ResolutionError, match="round and tie"):
        await _call(node, SELECT_ROUTE, {"round": {"a": _PASS, "b": _FAIL}}, "1")


# --- answer-collapse: the loop's single verbatim output ---------------------------


@pytest.mark.asyncio
async def test_answer_returns_the_selection_when_the_continuation_is_empty() -> None:
    node = _node()
    reply = await _call(node, ANSWER_ROUTE, {"selected": _outcome("round one"), "next": []}, "1")
    assert _answer(reply) == "round one"


@pytest.mark.asyncio
async def test_answer_prefers_the_continuation_outcome_when_one_exists() -> None:
    node = _node()
    reply = await _call(
        node,
        ANSWER_ROUTE,
        {"selected": _outcome("round one"), "next": [_outcome("round two", round=2)]},
        "1",
    )
    assert _answer(reply) == "round two"


@pytest.mark.asyncio
async def test_answer_treats_blank_continuation_text_as_empty() -> None:
    # An un-run iterate resolves to empty text, not an empty JSON array.
    node = _node()

    @node.endpoint("/collapse-probe")
    def collapse(request) -> str:
        return request.context

    payload = json.dumps({"selected": _outcome("round one"), "next": ""}, separators=(",", ":"))
    result = await node.evaluate(
        render(
            expr(
                src(text(payload), name="payload", weight=0.0),
                RelExpr(path=ANSWER_ROUTE, context="$payload", intent=Text("1")),
                intent=Text(""),
            )
        )
    )
    assert _answer(result.text) == "round one"


@pytest.mark.asyncio
async def test_answer_rejects_a_multi_outcome_continuation() -> None:
    node = _node()
    with pytest.raises(ResolutionError, match="at most one"):
        await _call(
            node,
            ANSWER_ROUTE,
            {"selected": _outcome("one"), "next": [_outcome("two"), _outcome("three")]},
            "1",
        )


# --- (3) the port record contract -------------------------------------------------


@pytest.mark.asyncio
async def test_gate_rejects_a_record_with_a_foreign_schema() -> None:
    node = _node()
    stranger = dict(_PASS, schema="screamingface.ifeval-check.v1")
    with pytest.raises(ResolutionError, match="check-surface record"):
        await _call(node, GATE_ROUTE, {"a": stranger, "b": _FAIL}, "continue:1:3")


@pytest.mark.asyncio
async def test_gate_rejects_a_record_missing_the_passed_field() -> None:
    node = _node()
    partial = {key: value for key, value in _PASS.items() if key != "passed"}
    with pytest.raises(ResolutionError, match="passed"):
        await _call(node, GATE_ROUTE, {"a": partial, "b": _FAIL}, "continue:1:3")


@pytest.mark.asyncio
async def test_gate_rejects_satisfaction_outside_the_unit_interval() -> None:
    node = _node()
    inflated = dict(_HALF, satisfaction=1.5)
    with pytest.raises(ResolutionError, match="satisfaction"):
        await _call(node, GATE_ROUTE, {"a": inflated, "b": _FAIL}, "tie:3:3")


@pytest.mark.asyncio
async def test_gate_accepts_records_carried_as_json_text() -> None:
    # A URL4 struct substitutes source outputs as text — the round object arrives
    # with each record as a JSON string, not a decoded object.
    node = _node()
    round_records = {"a": json.dumps(_PASS), "b": json.dumps(_FAIL)}
    reply = await _call(node, GATE_ROUTE, round_records, "continue:1:3")
    assert json.loads(reply) == []


@pytest.mark.asyncio
async def test_gate_rejects_answer_text_that_disagrees_with_its_invocation() -> None:
    node = _node()
    mismatched = dict(_PASS, invocation=encode_candidate_invocation("different", "stop", None))
    with pytest.raises(ResolutionError, match="must equal its Candidate Invocation text"):
        await _call(node, GATE_ROUTE, {"a": mismatched, "b": _FAIL}, "continue:1:3")


def test_the_member_floor_is_structural_not_a_label_mechanism_cap() -> None:
    assert MEMBER_LABEL_SCHEME == "lowercase-base26"
