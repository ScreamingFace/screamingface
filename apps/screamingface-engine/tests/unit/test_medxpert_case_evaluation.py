"""MedXpertQA per-Case envelopes and the route that packs them."""

from __future__ import annotations

import json
from typing import Any

import pytest

from screamingface_engine.benchmarks.evaluation import attempt_records_endpoint
from screamingface_engine.benchmarks.medxpert.case_evaluation import (
    CASE_EVALUATION_SCHEMA,
    CHECK_SCHEMA,
    bind_case_evaluation,
    decode_case_evaluation,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request


def _check_record(case_id: int = 1, letter: str = "C") -> dict[str, object]:
    return {"schema": CHECK_SCHEMA, "case_id": case_id, "answer": letter}


def _endpoint():
    return attempt_records_endpoint(
        label="MedXpertQA Case evaluation",
        item_name="Attempt",
        bind=bind_case_evaluation,
        error_context_head=300,
    )


def _call(context: str, intent: str = "1") -> Any:
    handler = _endpoint()
    return json.loads(handler(Request(path="/t", context=context, intent=intent, params={})))


def test_route_accepts_the_attempt_struct_the_expression_renders() -> None:
    """REGRESSION: the Board renders `{attempt_1: ...}`, an object — never a JSON array."""

    result = _call(json.dumps({"attempt_1": json.dumps(_check_record())}))

    assert result == {
        "schema": CASE_EVALUATION_SCHEMA,
        "case_id": 1,
        "attempts": [_check_record()],
    }


def test_route_packs_consecutive_attempts_in_order() -> None:
    context = json.dumps(
        {
            "attempt_1": json.dumps(_check_record(letter="A")),
            "attempt_2": json.dumps(_check_record(letter="B")),
        }
    )

    assert [a["answer"] for a in _call(context)["attempts"]] == ["A", "B"]


def test_route_rejects_a_gap_in_the_attempt_numbering() -> None:
    context = json.dumps({"attempt_1": json.dumps(_check_record()), "attempt_3": "{}"})

    with pytest.raises(ResolutionError, match="consecutive attempt_1..attempt_N"):
        _call(context)


def test_route_reraises_an_upstream_collected_failure() -> None:
    """A one-key {"error": ...} item is url4's capture of an UPSTREAM failure."""

    context = json.dumps({"attempt_1": json.dumps({"error": "candidate call ran out of tokens"})})

    with pytest.raises(ResolutionError, match="ran out of tokens"):
        _call(context)


def test_route_reports_the_context_head_on_a_bind_level_failure() -> None:
    context = json.dumps({"attempt_1": json.dumps(_check_record(case_id=2))})

    with pytest.raises(ResolutionError, match="context head: "):
        _call(context)


def test_route_rejects_a_context_that_is_not_json() -> None:
    """A decode failure surfaces bare — `error_context_head` only decorates bind-level
    errors, because json_object raises ResolutionError, which the handler does not catch.
    Shared with case_evaluation_endpoint; pinned here so a fix updates both knowingly."""

    with pytest.raises(ResolutionError, match="must be JSON: "):
        _call("not json at all")


def test_bind_rejects_an_attempt_from_another_case() -> None:
    with pytest.raises(ValueError, match="belongs to another Case"):
        bind_case_evaluation(1, [_check_record(case_id=2)])


def test_bind_rejects_an_attempt_without_the_check_schema() -> None:
    with pytest.raises(ValueError, match=f"must carry schema {CHECK_SCHEMA}"):
        bind_case_evaluation(1, [{"case_id": 1, "answer": "C"}])


def test_bind_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="at least one attempt"):
        bind_case_evaluation(1, [])


def test_decode_round_trips_what_bind_produced() -> None:
    bound = bind_case_evaluation(1, [_check_record()])

    assert decode_case_evaluation(bound, 1) == bound


def test_decode_rejects_unknown_fields() -> None:
    bound = bind_case_evaluation(1, [_check_record()]) | {"score": 1.0}

    with pytest.raises(ValueError, match=r"unknown fields \['score'\]"):
        decode_case_evaluation(bound, 1)


def test_decode_rejects_an_envelope_for_another_case() -> None:
    bound = bind_case_evaluation(1, [_check_record()])

    with pytest.raises(ValueError, match="belongs to another Case"):
        decode_case_evaluation(bound, 2)
