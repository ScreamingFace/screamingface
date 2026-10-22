"""Golden contract for the serving-spine migration (OME-1236).

OME-932 (owner-approved) adds early graded-result transport without changing
this scoring revision or the legacy batch routes. Request/result compatibility
is exercised in test_early_grade_compatibility; these pins protect exam identity
and public asset/route contracts, not a ban on additive transport changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.grading_endpoints import compact_json
from screamingface_engine.benchmarks.medxpert.definition import (
    AGGREGATE_ROUTE,
    CASE_GRADE_ROUTE,
    CASES_ROUTE,
    COMMIT_PROMPT_ROUTE,
    REVISION,
    ROUTE_PREFIX,
)
from screamingface_engine.benchmarks.medxpert.prepare import emit
from screamingface_engine.benchmarks.medxpert.runtime import (
    _cases,
    _check,
    commit_prompt,
    preflight,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

# Captured 2026-09-21 from the pre-migration benchmark (base of this branch); moved once on
# 2026-10-19 when medxpert declared withhold (OME-1642: the failure policy is identity).
_GOLDEN_REVISION = "1e5a3b8a461a52f7"

_OPTIONS = {"A": "aspirin", "B": "heparin", "C": "warfarin", "D": "apixaban", "E": "alteplase"}
_QUESTION = "Which agent is indicated? Answer Choices: " + " ".join(
    f"({letter}) {label}" for letter, label in _OPTIONS.items()
)


def _root(tmp_path: Path) -> Path:
    row = {
        "id": "Text-0",
        "question": _QUESTION,
        "options": _OPTIONS,
        "label": "E",
        "medical_task": "Diagnosis",
        "body_system": "Cardiovascular",
        "question_type": "Reasoning",
    }
    emit([row], tmp_path)
    return tmp_path


def test_revision_is_byte_identical_to_the_pre_migration_benchmark() -> None:
    assert REVISION == _GOLDEN_REVISION


def test_routes_resolve_at_the_recorded_addresses() -> None:
    assert ROUTE_PREFIX == f"/benchmarks/medxpert/{_GOLDEN_REVISION}"
    assert CASES_ROUTE == f"{ROUTE_PREFIX}/cases"
    # WHY no check route (spec §3.2): the check runs inside the case-evaluation code.
    assert COMMIT_PROMPT_ROUTE == f"{ROUTE_PREFIX}/commit-prompt"
    assert CASE_GRADE_ROUTE == f"{ROUTE_PREFIX}/case-evaluation"
    assert AGGREGATE_ROUTE == f"{ROUTE_PREFIX}/aggregate"


def test_check_record_is_byte_identical(tmp_path: Path) -> None:
    # The exact string the pre-migration `_check` produced for this fixture,
    # including field ORDER — the envelope participates in recorded protocol.
    # WHY compact_json of the record (spec §3.3): the check runs in process inside the
    # case-evaluation code, which writes the record into its row with this encoder.
    handler = _check(_root(tmp_path))
    commit = encode_candidate_invocation("the answer is (E) alteplase", "stop", None)

    record = compact_json(handler(1, commit, {"reasoning": "I think E."}))

    assert record == (
        '{"schema":"screamingface.medxpert-check.v1","case_id":1,"attempt":1,'
        '"answer":"E","answered":true,"status":"completed","refusal":null,'
        '"finish_reason":"stop","commit_output":"the answer is (E) alteplase",'
        '"reasoning":"I think E.","execution":null}'
    )


def test_served_rows_are_byte_identical(tmp_path: Path) -> None:
    served_bytes = _cases(_root(tmp_path))()

    assert served_bytes == (
        '[{"id":1,"case_id":"1","input":"' + _QUESTION + '",'
        '"cot_prompt":"Q: ' + _QUESTION + "\\nA: Let's think step by step.\","
        '"trigger":"Therefore, among A through E, the answer is"}]'
    )


def test_a_missing_answer_record_is_a_definition_error(tmp_path: Path) -> None:
    """Pin medxpert's per-benchmark deviation: a broken bundle is a DEFINITION error.

    WHY the direct `preflight` call (review of this PR): through `serve_cases`,
    a missing answer record trips `_build_public_cases`' own raise before the preflight
    ever runs, so the declaration's error class was unreachable from that path
    and its deletion survived the whole suite. This is the one test that dies
    if `preflight` stops raising `benchmark_definition_error`.
    """
    with pytest.raises(ResolutionError) as caught:
        preflight(_root(tmp_path), (9,))

    assert caught.value.code == "benchmark_definition_error"


_TURN_ONE = json.dumps(
    {"schema": "x", "output": 'Think ü "quoted"\nnext line $5 and $item'},
    ensure_ascii=False,
    separators=(",", ":"),
)
_TURN_TWO_ROW = {"id": 1, "input": "Q: pick $A\n(B) café 'x'", "trigger": "Answer: "}


async def _turn_two_input(expression: str, node: Url4Node) -> str:
    """Run ``expression`` over one Case; return what the turn-2 Candidate call would receive."""

    seen: list[str] = []
    node.data("/c", json.dumps([_TURN_TWO_ROW], ensure_ascii=False), media_type="application/json")
    node.endpoint("/turn1")(lambda _request: _TURN_ONE)
    node.endpoint("/turn2")(lambda request: seen.append(_old_or_new(request)) or "ok")
    node.code("/done")(lambda _call: "done")
    await node.evaluate(expression, env={"candidate": "recipe"})
    return seen[0]


def _old_or_new(request: Request) -> str:
    if request.context.startswith("{"):
        # The retired path: a struct context, decoded as `case_request.candidate_input` did.
        value = json.loads(request.context)["input"]
        return json.dumps(value) if isinstance(value, dict) else value
    return request.intent


@pytest.mark.asyncio
async def test_the_commit_prompt_is_byte_identical_to_the_retired_turn_two_input() -> None:
    """INVARIANT: the turn-2 model input does not move, so stored replies still serve it."""

    old = await _turn_two_input(
        "(e:0.0:/c*(r:0.0:/turn1?q=('x')!'y', a:0.0:/turn2?q=({input: {question: "
        "'$item.input', reasoning: '$r', trigger: '$item.trigger'}, case_id: '$item.id'})"
        "!'$candidate')!'$a')!'$e'",
        Url4Node("old"),
    )
    node = Url4Node("new")
    node.code("/commit-prompt")(commit_prompt)
    new = await _turn_two_input(
        "(e:0.0:/c*(r:0.0:/turn1?q=('x')!'y', p:0.0:(question=$item.input, reasoning=$r, "
        "trigger=$item.trigger)!/commit-prompt, a:0.0:/turn2?q=(recipe=$candidate)!'$p')"
        "!/done)!/done",
        node,
    )

    assert new == old
    assert json.loads(new) == {
        "question": _TURN_TWO_ROW["input"],
        "reasoning": _TURN_ONE,
        "trigger": "Answer: ",
    }
