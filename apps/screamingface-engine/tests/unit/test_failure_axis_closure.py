"""Closing the failure-code axis: undeclared codes cannot reach a report (OME-1234, PR c).

FEATURE: tell the researcher what kind of failure ended their run (OME-1233).
STORY: as a researcher, every failure code I read comes from the declared list —
a typo or a one-off spelling fails in CI, not in my report.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from screamingface_engine.benchmarks.aggregation import public_error
from screamingface_engine.benchmarks.contract import Failure


def _failure(code: str) -> Failure:
    return Failure(
        stage="grading",
        code=code,
        message="a message",
        retryable=None,
        case_id=1,
        metadata={},
    )


def test_an_undeclared_code_is_refused_loudly() -> None:
    # INVARIANT: the Failure model is the one place every published failure
    # passes through — refusing here means an undeclared code can never reach
    # a report, whichever board produced it.
    with pytest.raises(ValidationError, match="undeclared failure code"):
        _failure("a_code_nobody_declared")


def test_a_declared_code_still_passes() -> None:
    assert _failure("judge_reply_invalid").code == "judge_reply_invalid"


def test_declared_upstream_codes_pass_through_verbatim() -> None:
    # INVARIANT: the observed upstream vocabulary keeps its exact spellings —
    # existing reports and tests do not change meaning.
    diagnostic = public_error(
        {"code": "rate_limited", "message": "slow down", "retryable": True},
        default_code="grading_failed",
        default_message="fallback",
    )
    assert (diagnostic.code, diagnostic.source_code) == ("rate_limited", None)


def test_an_unknown_upstream_code_maps_to_the_declared_fallback() -> None:
    # WHY (owner decision, OME-1234): gateway churn must never crash a paid run
    # mid-flight — an unknown code becomes upstream_error, spelling preserved.
    diagnostic = public_error(
        {"code": "some_new_gateway_code", "message": "boom", "retryable": True},
        default_code="grading_failed",
        default_message="fallback",
    )
    assert diagnostic.code == "upstream_error"
    assert diagnostic.source_code == "some_new_gateway_code"
    assert diagnostic.retryable is True
    assert diagnostic.message == "boom"


def test_an_absent_upstream_code_keeps_the_declared_default() -> None:
    diagnostic = public_error(
        {"message": "boom"},
        default_code="grading_failed",
        default_message="fallback",
    )
    assert (diagnostic.code, diagnostic.source_code) == ("grading_failed", None)


def test_the_aigateway_http_family_is_declared() -> None:
    # INVARIANT: the connector's per-status codes are a closed FAMILY — the
    # status number is load-bearing (429 vs 500 drives retry advice), so they
    # pass as themselves rather than folding into upstream_error.
    assert _failure("aigateway_http_429").code == "aigateway_http_429"
    diagnostic = public_error(
        {"code": "aigateway_http_503", "message": "m", "retryable": True},
        default_code="grading_failed",
        default_message="fallback",
    )
    assert (diagnostic.code, diagnostic.source_code) == ("aigateway_http_503", None)


def test_a_malformed_family_spelling_is_still_refused() -> None:
    with pytest.raises(ValidationError, match="undeclared failure code"):
        _failure("aigateway_http_9999")


def test_a_folded_code_surfaces_its_source_spelling_in_metadata() -> None:
    # INVARIANT: the fold never destroys information — the raw upstream spelling
    # rides in metadata.source_code so on-call can see what the gateway said.
    from screamingface_engine.benchmarks.aggregation import (
        SelectedCase,
        grading_failure_case_result,
    )
    from screamingface_engine.benchmarks.contract import encode_candidate_invocation
    from screamingface_engine.benchmarks.evaluation import candidate_answer

    case = grading_failure_case_result(
        selected_case=SelectedCase(case_id=1, input="q", metadata={}),
        candidate=candidate_answer(encode_candidate_invocation("a", "stop", None)),
        error={"code": "some_new_gateway_code", "message": "boom", "retryable": True},
        method="rubric",
    )
    failure = case.failures[0]
    assert failure.code == "upstream_error"
    assert failure.metadata["source_code"] == "some_new_gateway_code"
