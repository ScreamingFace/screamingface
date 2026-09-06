"""A Case that represents a refusal states which side refused: provider or model.

INVARIANT defended: the Engine's runner classifies a refused turn from two
provider-verbatim signals it already publishes on every Case (OME-745,
`runner/model_response.py`): a `content_filter` finish reason means the provider's
filter terminated the call; a non-null `refusal` field carries the model's own
refusal message. The client derives `refusal_kind` from exactly those wire fields —
never from answer text, never serialized, and never guessed when neither signal is
present. Since OME-1037 there is no `refused` case status: the kind is read off a
scored Case carrying refusal text (the benchmark graded the decline) or a failed
Case carrying a `provider_refusal` failure (it could not be graded).
"""

from __future__ import annotations

from typing import Any

import pytest

import screamingface as sf
from screamingface._evaluation.results import _case_result


def _graded_refusal_payload(finish_reason: str | None, refusal: str) -> dict[str, Any]:
    return {
        "status": "scored",
        "case_id": 1,
        "input": "A clinical question",
        "output": None,
        "finish_reason": finish_reason,
        "refusal": refusal,
        "stop_reason": None,
        "rounds_executed": None,
        "grade": {"method": "rubric", "score": 0.0, "metrics": {}, "checks": []},
        "failures": [],
        "metadata": {},
    }


def _ungradeable_refusal_payload(finish_reason: str | None, refusal: str | None) -> dict[str, Any]:
    return {
        "status": "failed",
        "case_id": 1,
        "input": "A clinical question",
        "output": None,
        "finish_reason": finish_reason,
        "refusal": refusal,
        "stop_reason": None,
        "rounds_executed": None,
        "grade": {"method": "rubric", "score": None, "metrics": {}, "checks": []},
        "failures": [
            {
                "stage": "candidate",
                "code": "provider_refusal",
                "message": "provider refused the request",
                "retryable": False,
                "case_id": 1,
                "metadata": {},
            }
        ],
        "metadata": {},
    }


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        pytest.param(
            _ungradeable_refusal_payload("content_filter", None),
            "provider_declined",
            id="content-filter-is-the-provider-declining",
        ),
        pytest.param(
            _graded_refusal_payload("stop", "I can't help with that request."),
            "model_refusal",
            id="a-refusal-message-is-the-model-refusing",
        ),
        pytest.param(
            _graded_refusal_payload(None, "I can't help with that request."),
            "model_refusal",
            id="the-message-alone-decides-without-a-finish-reason",
        ),
        pytest.param(
            _graded_refusal_payload("content_filter", "exact refusal"),
            "provider_declined",
            id="both-signals-present-the-provider-wins",
        ),
        pytest.param(
            _ungradeable_refusal_payload(None, None),
            None,
            id="a-refusal-with-neither-signal-loads-with-unknown-kind",
        ),
    ],
)
def test_the_kind_follows_the_engine_classifiers_signal_table(
    payload: dict[str, Any], kind: str | None
) -> None:
    # WHY: one row per line of the Engine classifier's own truth table
    # (`runner/model_response.py`, OME-745): `content_filter` means the provider's
    # filter terminated the call and is checked FIRST (so a filtered turn with
    # refusal text tagging along still reads as the provider declining); a
    # non-null `refusal` — the model's own refusal message — alone decides even
    # without a finish reason; and a refusal payload carrying neither signal
    # still loads, with the kind unknown — never a crash and never a guess.
    assert _case_result(payload).refusal_kind == kind


def test_a_provider_402_failure_is_no_kind_of_refusal() -> None:
    # WHY: a provider that errors (e.g. a 402) produces a FAILED Case without a
    # provider_refusal failure — it must not read as a model refusal, or as any
    # refusal at all.
    payload: dict[str, Any] = {
        "status": "failed",
        "case_id": 1,
        "input": "A question",
        "output": None,
        "finish_reason": None,
        "refusal": None,
        "stop_reason": None,
        "rounds_executed": None,
        "grade": None,
        "failures": [
            {
                "stage": "candidate",
                "code": "provider_error",
                "message": "402 Payment Required",
                "retryable": True,
                "case_id": 1,
                "metadata": {},
            }
        ],
        "metadata": {},
    }

    assert _case_result(payload).refusal_kind is None


def test_an_answered_scored_case_has_no_refusal_kind() -> None:
    # WHY: the kind is a reading of Cases that REPRESENT a refusal only — an
    # ordinary graded answer carries none, whatever its finish reason.
    payload = _graded_refusal_payload("stop", "unused")
    payload.update(output="Four.", refusal=None)
    payload["grade"] = {"method": "rubric", "score": 1.0, "metrics": {}, "checks": []}

    assert _case_result(payload).refusal_kind is None


def test_the_derived_kind_is_never_serialized() -> None:
    # WHY: no wire change — `to_dict()` stays byte-identical to the payload, so
    # saved reports round-trip unchanged and old readers see nothing new.
    payload = _ungradeable_refusal_payload("content_filter", None)

    exported = _case_result(payload).to_dict()

    assert exported == payload
    assert "refusal_kind" not in exported


def test_a_locally_built_refusal_case_derives_the_same_kind() -> None:
    # WHY: the kind is a pure function of the Case fields, so a directly
    # constructed value and a wire-decoded one can never disagree.
    case = sf.CaseResult(
        status="scored",
        case_id=1,
        input="A clinical question",
        output=None,
        finish_reason="content_filter",
        refusal="I can't help with that request.",
        grade=sf.CaseGrade(method="rubric", score=0.0, metrics={}, checks=()),
        failures=(),
        metadata={},
    )

    assert case.refusal_kind == "provider_declined"


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        (_ungradeable_refusal_payload("content_filter", None), "provider_declined"),
        (
            _graded_refusal_payload("stop", "I can't help with that request."),
            "model_refusal",
        ),
    ],
)
def test_the_kind_survives_a_save_and_reload_round_trip(payload: dict[str, Any], kind: str) -> None:
    # WHY: the acceptance path — a refusal Case round-tripping from the real
    # engine payload shape states which of the two kinds it was, on both sides
    # of a save/reload.
    reloaded = _case_result(_case_result(payload).to_dict())

    assert reloaded.refusal_kind == kind
