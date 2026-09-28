"""The client mirrors the OME-1037 case-status split: no `refused` status.

INVARIANT defended: the wire vocabulary carries one meaning per status value. A
refusal the benchmark graded decodes as an ordinary `scored` case carrying
`refusal` text (exactly one of `output`/`refusal` set); a refusal the benchmark
could not grade decodes as a `failed` case whose failures include the
`provider_refusal` code — the only failed shape allowed to keep refusal text as
evidence. The pre-split `refused` status is rejected loudly, never reinterpreted.
"""

from __future__ import annotations

from typing import Any

import pytest

import screamingface as sf
from screamingface._evaluation.results import _case_result


def _scored_refusal_payload(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "status": "scored",
        "case_id": 1,
        "input": "A deceptive prompt.",
        "output": None,
        "finish_reason": "stop",
        "refusal": "I will not help with that.",
        "stop_reason": None,
        "rounds_executed": None,
        "grade": {"method": "rubric", "score": 1.0, "metrics": {}, "checks": []},
        "failures": [],
        "metadata": {},
    }
    values.update(overrides)
    return values


def _provider_refusal_failure(code: str = "provider_refusal") -> dict[str, Any]:
    return {
        "stage": "candidate",
        "code": code,
        "message": "provider refused the request",
        "retryable": False,
        "case_id": 1,
        "metadata": {},
    }


def _failed_refusal_payload(**overrides: Any) -> dict[str, Any]:
    values = _scored_refusal_payload(
        status="failed",
        finish_reason="content_filter",
        grade={"method": "rubric", "score": None, "metrics": {}, "checks": []},
        failures=[_provider_refusal_failure()],
    )
    values.update(overrides)
    return values


def test_the_refused_status_is_rejected_by_the_decoder() -> None:
    # WHY: `refused` meant "provider declined" in most benchmarks and "correct
    # answer" in DRACO — after OME-1037 the value no longer exists on the wire,
    # and an Engine still emitting it must fail loudly, never load ambiguously.
    with pytest.raises(sf.ExecutionError, match="status"):
        _case_result(_scored_refusal_payload(status="refused"))


def test_a_graded_refusal_decodes_as_a_scored_case_with_refusal_text() -> None:
    case = _case_result(_scored_refusal_payload())

    assert case.status == "scored"
    assert case.output is None
    assert case.refusal == "I will not help with that."
    assert case.grade is not None and case.grade.score == 1.0


@pytest.mark.parametrize(
    ("output", "refusal"),
    [
        pytest.param("An answer.", "I refuse.", id="both"),
        pytest.param(None, None, id="neither"),
    ],
)
def test_a_scored_case_carries_exactly_one_of_output_and_refusal(
    output: str | None, refusal: str | None
) -> None:
    with pytest.raises(sf.ExecutionError):
        _case_result(_scored_refusal_payload(output=output, refusal=refusal))


def test_an_ungradeable_refusal_decodes_as_failed_with_provider_refusal() -> None:
    case = _case_result(_failed_refusal_payload())

    assert case.status == "failed"
    assert case.refusal == "I will not help with that."
    assert [failure.code for failure in case.failures] == ["provider_refusal"]


def test_a_failed_case_without_provider_refusal_stays_refusal_free() -> None:
    # INVARIANT: refusal text on a failed case is provider_refusal evidence only.
    with pytest.raises(sf.ExecutionError, match="provider_refusal"):
        _case_result(_failed_refusal_payload(failures=[_provider_refusal_failure("case_error")]))


def test_a_directly_built_value_enforces_the_same_split() -> None:
    # WHY: the SDK's directly constructed values and its wire decode share one
    # validator, so a test fixture cannot build a shape the Engine cannot emit.
    legacy_fields: dict[str, Any] = {
        "status": "refused",  # the rejected legacy value, typed loosely on purpose
        "case_id": 1,
        "input": "A deceptive prompt.",
        "output": None,
        "finish_reason": "stop",
        "grade": None,
        "failures": (),
        "metadata": {},
    }

    with pytest.raises(ValueError, match="scored|failed"):
        sf.CaseResult(**legacy_fields)


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        pytest.param(_scored_refusal_payload(), "model_refusal", id="graded-model-refusal"),
        pytest.param(
            _scored_refusal_payload(finish_reason="content_filter"),
            "provider_declined",
            id="filtered-turn-with-text-still-reads-provider",
        ),
        pytest.param(_failed_refusal_payload(), "provider_declined", id="textless-decline"),
    ],
)
def test_refusal_kind_reads_the_same_signals_across_both_new_homes(
    payload: dict[str, Any], kind: str
) -> None:
    # WHY: OME-745's signal table survives the status split — `content_filter`
    # first (the provider's filter terminated the call), else refusal text (the
    # model's own decline). The gate moves from `status == "refused"` to "this
    # case represents a refusal": scored-with-refusal or failed-with-
    # provider_refusal.
    assert _case_result(payload).refusal_kind == kind


def test_refusal_kind_stays_none_for_ordinary_outcomes() -> None:
    answered = _scored_refusal_payload(output="Four.", refusal=None)
    plain_failure = _failed_refusal_payload(
        refusal=None,
        finish_reason=None,
        failures=[_provider_refusal_failure("case_error")],
    )

    assert _case_result(answered).refusal_kind is None
    assert _case_result(plain_failure).refusal_kind is None
