"""ContractEval per-Case envelopes and the route that packs them."""

from __future__ import annotations

import json
from typing import Any

import pytest

from screamingface_engine.benchmarks.contracteval.case_evaluation import (
    CASE_EVALUATION_SCHEMA,
    CHECK_SCHEMA,
    bind_case_evaluation,
    decode_case_evaluation,
)
from screamingface_engine.benchmarks.evaluation import attempt_records_endpoint
from url4.core.errors import ResolutionError
from url4.peer.server import Request


def _record(case_id: int = 1, *, correct: bool = True) -> dict[str, object]:
    return {
        "schema": CHECK_SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "correct": correct,
        "is_positive": True,
        "abstained": False,
        "jaccard": 0.75,
    }


def _call(context: str, intent: str = "1") -> Any:
    handler = attempt_records_endpoint(
        label="ContractEval Case evaluation",
        item_name="Attempt",
        bind=bind_case_evaluation,
        error_context_head=300,
    )
    return json.loads(handler(Request(path="/t", context=context, intent=intent, params={})))


def test_the_route_accepts_the_attempt_struct_the_expression_renders() -> None:
    """REGRESSION (OME-1126): the board renders `{attempt_1: ...}`, an object. The array-shaped
    `case_evaluation_endpoint` is for rubric `iterate` fan-outs and fails on this shape."""

    result = _call(json.dumps({"attempt_1": json.dumps(_record())}))

    assert result == {
        "schema": CASE_EVALUATION_SCHEMA,
        "case_id": 1,
        "attempts": [_record()],
    }


def test_the_route_reraises_an_upstream_collected_failure() -> None:
    context = json.dumps({"attempt_1": json.dumps({"error": "the candidate call timed out"})})

    with pytest.raises(ResolutionError, match="timed out"):
        _call(context)


def test_bind_rejects_an_attempt_from_another_case() -> None:
    with pytest.raises(ValueError, match="belongs to another Case"):
        bind_case_evaluation(1, [_record(case_id=2)])


def test_bind_rejects_an_attempt_without_the_check_schema() -> None:
    with pytest.raises(ValueError, match=f"must carry schema {CHECK_SCHEMA}"):
        bind_case_evaluation(1, [{"case_id": 1, "correct": True}])


def test_bind_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="at least one attempt"):
        bind_case_evaluation(1, [])


def test_decode_round_trips_what_bind_produced() -> None:
    bound = bind_case_evaluation(1, [_record()])

    assert decode_case_evaluation(bound, 1) == bound


def test_decode_rejects_unknown_fields() -> None:
    bound = bind_case_evaluation(1, [_record()]) | {"score": 1.0}

    with pytest.raises(ValueError, match=r"unknown fields \['score'\]"):
        decode_case_evaluation(bound, 1)


def test_decode_rejects_an_envelope_for_another_case() -> None:
    bound = bind_case_evaluation(1, [_record()])

    with pytest.raises(ValueError, match="belongs to another Case"):
        decode_case_evaluation(bound, 2)
