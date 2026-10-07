"""MuSiQue-Ans per-Case envelopes and the route that packs them.

INVARIANT under test: no inference. The aggregate grades only what these envelopes carry, so
a check record missing its committed answer or its support numbers must fail HERE, by name,
rather than reach the scorer as an empty answer that silently scores 0.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from screamingface_engine.benchmarks.grading_endpoints import attempt_records_endpoint
from screamingface_engine.benchmarks.musique.case_grade import (
    CASE_GRADE_SCHEMA,
    CHECK_SCHEMA,
    build_case_grade,
    decode_case_grade,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request

_VERDICT_FIELDS: tuple[str, ...] = ("answer", "support", "answer_line", "support_line")


def _record(case_id: int = 1, **changes: object) -> dict[str, object]:
    """One check record for the spec's first reply: `Supporting paragraphs: 10, 5`,
    `Answer: Miquette Giraudy`."""

    record: dict[str, object] = {
        "schema": CHECK_SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "answer": "Miquette Giraudy",
        "support": [5, 10],
        "answer_line": True,
        "support_line": True,
    }
    return record | changes


def _call(context: str, intent: str = "1") -> Any:
    """Drive the case-evaluation route the way `install_benchmark` registers it."""

    handler = attempt_records_endpoint(
        label="MuSiQue-Ans Case evaluation",
        item_name="Attempt",
        bind=build_case_grade,
        error_context_head=300,
    )
    return json.loads(handler(Request(path="/t", context=context, intent=intent, params={})))


def test_the_route_accepts_the_attempt_struct_the_expression_renders() -> None:
    """REGRESSION (OME-1126): the expression renders `{attempt_1: ...}`, an object."""

    result = _call(json.dumps({"attempt_1": json.dumps(_record())}))

    assert result == {"schema": CASE_GRADE_SCHEMA, "case_id": 1, "attempts": [_record()]}


def test_the_route_reraises_an_upstream_collected_failure() -> None:
    """A failed check reaches the aggregate as a named grading failure, not as a record."""

    context: str = json.dumps({"attempt_1": json.dumps({"error": "the check could not run"})})

    with pytest.raises(ResolutionError, match="could not run"):
        _call(context)


def test_bind_rejects_an_attempt_from_another_case() -> None:
    with pytest.raises(ValueError, match="belongs to another Case"):
        build_case_grade(1, [_record(case_id=2)])


def test_bind_rejects_an_attempt_without_the_check_schema() -> None:
    with pytest.raises(ValueError, match=f"must carry schema {CHECK_SCHEMA}"):
        build_case_grade(1, [{"case_id": 1, "answer": "x"}])


def test_bind_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="at least one attempt"):
        build_case_grade(1, [])


def test_decode_round_trips_what_bind_produced() -> None:
    bound: dict[str, Any] = build_case_grade(1, [_record()])

    assert decode_case_grade(bound, 1) == bound


def test_decode_rejects_unknown_fields() -> None:
    """A score smuggled onto the envelope must not be read — grading computes it from the key."""

    bound: dict[str, Any] = build_case_grade(1, [_record()]) | {"score": 1.0}

    with pytest.raises(ValueError, match=r"unknown fields \['score'\]"):
        decode_case_grade(bound, 1)


def test_decode_rejects_an_envelope_for_another_case() -> None:
    with pytest.raises(ValueError, match="belongs to another Case"):
        decode_case_grade(build_case_grade(1, [_record()]), 2)


@pytest.mark.parametrize("missing", _VERDICT_FIELDS)
def test_bind_rejects_a_record_missing_a_verdict_field(missing: str) -> None:
    record: dict[str, object] = _record()
    del record[missing]

    with pytest.raises(ValueError, match=missing):
        build_case_grade(1, [record])


@pytest.mark.parametrize("missing", _VERDICT_FIELDS)
def test_decode_rejects_a_record_missing_a_verdict_field(missing: str) -> None:
    bound: dict[str, Any] = build_case_grade(1, [_record()])
    del bound["attempts"][0][missing]

    with pytest.raises(ValueError, match=missing):
        decode_case_grade(bound, 1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("answer", None),
        ("answer_line", "yes"),
        ("support_line", 1),
        ("support", "5, 10"),
        # WHY a bool is refused: JSON `true` is an int to Python, and would cite paragraph 1.
        ("support", [True]),
        ("support", [-1]),
        ("support", [5.0]),
    ],
)
def test_an_ill_typed_verdict_field_is_refused(field: str, value: object) -> None:
    """Each type the scorer relies on is checked on the way in, so a drifted check record
    fails by field name instead of becoming a wrong score."""

    with pytest.raises(ValueError, match=field):
        build_case_grade(1, [_record() | {field: value}])


def test_an_empty_answer_and_empty_support_are_valid_facts() -> None:
    """A reply with no `Answer:` value and no cited numbers is a graded Case (spec F4, F5), so
    the envelope carries it; only the scorer decides what it earns."""

    bound: dict[str, Any] = build_case_grade(
        1, [_record(answer="", support=[], answer_line=False, support_line=False)]
    )

    assert bound["attempts"][0]["answer"] == ""
    assert bound["attempts"][0]["support"] == []
