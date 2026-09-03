"""A refused Case states which side refused: the provider declined, or the model.

INVARIANT defended: the Engine's runner classifies a refused turn from two
provider-verbatim signals it already publishes on every Case (OME-745,
`runner/model_response.py`): a `content_filter` finish reason means the provider's
filter terminated the call; a non-null `refusal` field carries the model's own
refusal message. The client derives `refusal_kind` from exactly those wire fields —
never from answer text, never serialized, and never guessed when neither signal is
present (older payloads stay loadable with kind `None`).
"""

from __future__ import annotations

from typing import Any

import pytest

import screamingface as sf
from screamingface._evaluation.results import _case_result


def _refused_payload(finish_reason: str | None, refusal: str | None) -> dict[str, Any]:
    return {
        "status": "refused",
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


@pytest.mark.parametrize(
    ("finish_reason", "refusal", "kind"),
    [
        pytest.param(
            "content_filter",
            None,
            "provider_declined",
            id="content-filter-is-the-provider-declining",
        ),
        pytest.param(
            "stop",
            "I can't help with that request.",
            "model_refusal",
            id="a-refusal-message-is-the-model-refusing",
        ),
        pytest.param(
            None,
            "I can't help with that request.",
            "model_refusal",
            id="the-message-alone-decides-without-a-finish-reason",
        ),
        pytest.param(
            "content_filter",
            "exact refusal",
            "provider_declined",
            id="both-signals-present-the-provider-wins",
        ),
        pytest.param(
            None,
            None,
            None,
            id="a-pre-OME-745-payload-loads-with-unknown-kind",
        ),
    ],
)
def test_the_kind_follows_the_engine_classifiers_signal_table(
    finish_reason: str | None, refusal: str | None, kind: str | None
) -> None:
    # WHY: one row per line of the Engine classifier's own truth table
    # (`runner/model_response.py`, OME-745): `content_filter` means the provider's
    # filter terminated the call and is checked FIRST (so a filtered turn with
    # refusal text tagging along still reads as the provider declining); a
    # non-null `refusal` — the model's own refusal message — alone decides even
    # without a finish reason (OME-745 captured the two independently); and a
    # pre-OME-745 payload carrying neither signal still loads, with the kind
    # unknown — never a crash and never a guess.
    case = _case_result(_refused_payload(finish_reason, refusal))

    assert case.status == "refused"
    assert case.refusal_kind == kind


def test_a_provider_402_failure_is_no_kind_of_refusal() -> None:
    # WHY: a provider that errors (e.g. a 402) produces a FAILED Case — it must not
    # read as a model refusal, or as any refusal at all.
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


def test_a_scored_case_has_no_refusal_kind() -> None:
    # WHY: `content_filter` never reaches a scored Case in practice, but the kind
    # is a reading of REFUSED Cases only — status semantics stay untouched.
    payload = _refused_payload("stop", None)
    payload.update(status="scored", output="Four.")
    payload["grade"] = {"method": "rubric", "score": 1.0, "metrics": {}, "checks": []}

    assert _case_result(payload).refusal_kind is None


def test_the_derived_kind_is_never_serialized() -> None:
    # WHY: no wire change — `to_dict()` stays byte-identical to the payload, so
    # saved reports round-trip unchanged and old readers see nothing new.
    payload = _refused_payload("content_filter", None)

    exported = _case_result(payload).to_dict()

    assert exported == payload
    assert "refusal_kind" not in exported


def test_a_locally_built_refused_case_derives_the_same_kind() -> None:
    # WHY: the kind is a pure function of the Case fields, so a directly
    # constructed value and a wire-decoded one can never disagree.
    case = sf.CaseResult(
        status="refused",
        case_id=1,
        input="A clinical question",
        output=None,
        finish_reason="content_filter",
        grade=sf.CaseGrade(method="rubric", score=0.0, metrics={}, checks=()),
        failures=(),
        metadata={},
    )

    assert case.refusal_kind == "provider_declined"


@pytest.mark.parametrize(
    ("finish_reason", "refusal", "kind"),
    [
        ("content_filter", None, "provider_declined"),
        ("stop", "I can't help with that request.", "model_refusal"),
    ],
)
def test_the_kind_survives_a_save_and_reload_round_trip(
    finish_reason: str | None, refusal: str | None, kind: str
) -> None:
    # WHY: the acceptance path — a refused Case round-tripping from the real
    # engine payload shape states which of the two kinds it was, on both sides
    # of a save/reload.
    payload = _refused_payload(finish_reason, refusal)

    reloaded = _case_result(_case_result(payload).to_dict())

    assert reloaded.refusal_kind == kind
