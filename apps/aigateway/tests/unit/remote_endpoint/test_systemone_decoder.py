"""The one decoder of a SystemOne choice answer, and the native request it answers (contract C7).

# FEATURE: Router Recipe extension Unit 5.1 — Laya and Jev answer one `choice` question with label
# probabilities; the Gateway projects them to `classification-scores-v1` in returned order.
# INVARIANT: anything but one well-formed `choice` answer within the target's limits, with no
# reported lost input, is None, which dispatch and readiness both read as the provider's error.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aigateway.plugins.remote_endpoint.definitions import ChoiceTarget
from aigateway.plugins.remote_endpoint.limits import ClassifierLimits
from aigateway.plugins.remote_endpoint.systemone import (
    choice_request,
    decode_choice,
    probe_choice,
)

from .choice_upstream import LIMITS, choice_input, native_answer
from .fixtures import JSON_TYPE

TARGET_LIMITS = ClassifierLimits(**LIMITS)
GOOD = {"b": 0.25, "a": 0.5, "c": 0.25}


def _decode(value: Any, *, content_type: str | None = JSON_TYPE) -> Any:
    return decode_choice(content_type, json.dumps(value).encode(), limits=TARGET_LIMITS)


def _with_answer(**answer: Any) -> dict[str, Any]:
    body = native_answer(GOOD)
    body["answers"]["choice"].update(answer)
    return body


def test_a_well_formed_answer_projects_in_returned_order() -> None:
    assert _decode(native_answer(GOOD)) == [
        {"label": "b", "score": 0.25},
        {"label": "a", "score": 0.5},
        {"label": "c", "score": 0.25},
    ]


@pytest.mark.parametrize(
    "probabilities",
    [{"a": 0}, {"a": 1}, {"a": 0.0001, "b": 0.0001}, dict.fromkeys("abcdefgh", 0.125)],
    ids=["zero", "one", "unnormalized", "max-labels"],
)
def test_edge_answers_are_accepted(probabilities: dict[str, float]) -> None:
    decoded = _decode(native_answer(probabilities))
    assert [item["label"] for item in decoded] == list(probabilities)


def test_unchecked_fields_are_neither_checked_nor_projected() -> None:
    body = native_answer(GOOD, routing={"x": [1]}, model=None)
    body["answers"]["choice"].update(choice=7, confidence="high", answer_confidence=None)
    assert _decode(body) == _decode(native_answer(GOOD))


def test_a_null_error_is_no_error() -> None:
    # WHY: as for a chat completion, only a non-null `error` reports a failure.
    body = native_answer(GOOD, error=None)
    body["answers"]["choice"]["error"] = None
    assert _decode(body) == _decode(native_answer(GOOD))


def test_absent_and_clean_usage_are_accepted() -> None:
    clean = {"truncated": False, "state_tokens_dropped": 0, "truncated_questions": [], "n": 5}
    assert _decode(native_answer(GOOD, usage=clean)) is not None


MALFORMED: dict[str, Any] = {
    "not-an-object": [native_answer(GOOD)],
    "no-answers": {"model": "m"},
    "answers-not-an-object": {"answers": [1]},
    "other-question": {"answers": {"other": native_answer(GOOD)["answers"]["choice"]}},
    "two-questions": {
        "answers": {
            "choice": native_answer(GOOD)["answers"]["choice"],
            "extra": native_answer(GOOD)["answers"]["choice"],
        }
    },
    "answer-not-an-object": {"answers": {"choice": "a"}},
    "wrong-answer-type": _with_answer(type="score"),
    "no-answer-type": {"answers": {"choice": {"probabilities": GOOD}}},
    "probabilities-a-list": _with_answer(probabilities=[["a", 0.5]]),
    "empty-probabilities": _with_answer(probabilities={}),
    "too-many-labels": _with_answer(probabilities=dict.fromkeys("abcdefghi", 0.1)),
    "empty-label": _with_answer(probabilities={"": 0.5}),
    "control-label": _with_answer(probabilities={"a\tb": 0.5}),
    "long-label": _with_answer(probabilities={"x" * 17: 0.5}),
    "long-utf8-label": _with_answer(probabilities={"é" * 9: 0.5}),
    "boolean": _with_answer(probabilities={"a": True}),
    "string": _with_answer(probabilities={"a": "0.5"}),
    "null": _with_answer(probabilities={"a": None}),
    "negative": _with_answer(probabilities={"a": -0.01}),
    "above-one": _with_answer(probabilities={"a": 1.01}),
    "truncated": native_answer(GOOD, usage={"truncated": True}),
    "truncated-not-a-bool": native_answer(GOOD, usage={"truncated": 0}),
    "tokens-dropped": native_answer(GOOD, usage={"state_tokens_dropped": 3}),
    "tokens-dropped-negative": native_answer(GOOD, usage={"state_tokens_dropped": -1}),
    "tokens-dropped-bool": native_answer(GOOD, usage={"state_tokens_dropped": False}),
    "tokens-dropped-float": native_answer(GOOD, usage={"state_tokens_dropped": 0.0}),
    "truncated-questions": native_answer(GOOD, usage={"truncated_questions": ["choice"]}),
    "truncated-questions-not-a-list": native_answer(GOOD, usage={"truncated_questions": None}),
    "colliding-options": native_answer(GOOD, usage={"options": {"a": ["b"]}}),
    "usage-not-an-object": native_answer(GOOD, usage=None),
    # WHY: probabilities beside a reported failure are not an answer; a Router reading them
    # would select a branch, and pay for it, on a classifier that said it failed.
    "error-beside-the-answers": native_answer(GOOD, error={"message": "failed"}),
    "error-text-beside-the-answers": native_answer(GOOD, error="failed"),
    "empty-error-beside-the-answers": native_answer(GOOD, error={}),
    "error-on-the-answer": _with_answer(error={"message": "failed"}),
    "false-error-on-the-answer": _with_answer(error=False),
}


@pytest.mark.parametrize("value", MALFORMED.values(), ids=MALFORMED.keys())
def test_a_malformed_answer_is_none(value: Any) -> None:
    assert _decode(value) is None


RAW: dict[str, tuple[str | None, bytes]] = {
    "repeated-probability-key": (
        JSON_TYPE,
        b'{"answers":{"choice":{"type":"choice","probabilities":{"a":0.9,"a":0.1}}}}',
    ),
    "repeated-answers-key": (
        JSON_TYPE,
        b'{"answers":{"choice":{"type":"choice","probabilities":{"a":0.9}},'
        b'"choice":{"type":"choice","probabilities":{"b":0.9}}}}',
    ),
    "nan": (JSON_TYPE, b'{"answers":{"choice":{"type":"choice","probabilities":{"a":NaN}}}}'),
    "infinity": (
        JSON_TYPE,
        b'{"answers":{"choice":{"type":"choice","probabilities":{"a":Infinity}}}}',
    ),
    "html": ("text/html", json.dumps(native_answer(GOOD)).encode()),
    "no-content-type": (None, json.dumps(native_answer(GOOD)).encode()),
    "not-json": (JSON_TYPE, b"{"),
    "lone-surrogate-label": (
        JSON_TYPE,
        b'{"answers":{"choice":{"type":"choice","probabilities":{"\\ud800":0.5}}}}',
    ),
}


@pytest.mark.parametrize(("content_type", "body"), RAW.values(), ids=RAW.keys())
def test_a_broken_envelope_is_none(content_type: str | None, body: bytes) -> None:
    assert decode_choice(content_type, body, limits=TARGET_LIMITS) is None


def test_the_native_request_holds_exactly_the_common_subset() -> None:
    laya = ChoiceTarget(alias="r", request_path="/v1/systemone", limits=TARGET_LIMITS)
    jev = ChoiceTarget(
        alias="r", request_path="/v1/systemone", limits=TARGET_LIMITS, upstream_model="jev/m"
    )
    value = choice_input("t")
    question = {
        "type": "choice",
        "instructions": value["instructions"],
        "criteria": {o["label"]: o["description"] for o in value["options"]},
    }
    assert choice_request(laya, value) == {
        "state": {"body": "t"},
        "questions": {"choice": question},
    }
    assert choice_request(jev, value) == {
        "model": "jev/m",
        "state": {"body": "t"},
        "questions": {"choice": question},
    }


@pytest.mark.parametrize("size", [1, 2, 4, 64])
def test_the_synthetic_probe_fits_any_valid_limits(size: int) -> None:
    from aigateway.core.classification_input import first_exceeded_limit, parse_choice_input

    limits = ClassifierLimits(
        max_labels=size,
        max_label_bytes=size,
        max_text_chars=size,
        max_options=1,
        max_description_chars=size,
        max_instructions_chars=size,
    )
    probe = probe_choice(limits)
    assert parse_choice_input(probe) == probe
    assert first_exceeded_limit(probe, LIMITS | limits.row()) is None
