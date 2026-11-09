"""Conservative eligibility for forgiving unanswered frozen-copy calls (OME-1775)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from screamingface_engine.benchmarks.contract import CaseResult, Failure
from screamingface_engine.benchmarks.failure_classes import TIME_BASED_CODES


def replay_stable_failure(case: CaseResult) -> bool:
    """R1 needs positive failure evidence, not merely the absence of a timeout.

    INVARIANT: every Attempt must fail deterministically. A transient later Attempt can recover
    on replay even though the fold kept only the first Attempt's failures on the Case.
    The tally separately requires a stored response at the cancelled call's case/attempt key.
    """
    results = [case, *(case.attempts or ())]
    return (
        case.status == "failed"
        and not _failed_on_time(case)
        and all(
            result.failures and all(_token_cap(f) for f in result.failures) for result in results
        )
    )


def _token_cap(failure: Failure) -> bool:
    """Only the candidate's deterministic token-cap failure is currently supported."""
    source = failure.metadata.get("source_error")
    nested = source if isinstance(source, Mapping) else {}
    code = nested.get("code", failure.code)
    # WHY: wrappers from shared grading retain the original code; an unknown source_code or
    # retry advice must never accidentally gain the exception through a familiar outer code.
    return (
        failure.stage == "candidate"
        and failure.retryable is False
        and code == "model_token_cap"
        and failure.metadata.get("source_code", code) == code
        and nested.get("source_code", code) == code
        and nested.get("retryable", False) is False
    )


def _failed_on_time(case: CaseResult) -> bool:
    """True when wall time caused a failure of the Case or of one of its Attempts (OME-1775 R1).

    WHY each Attempt: when no Attempt scored, the Attempt fold keeps only Attempt 1's failures on
    the Case, so a later Attempt's timeout is only in ``case.attempts``.
    """
    attempt_failures = [failure for attempt in case.attempts or () for failure in attempt.failures]
    return any(_time_based(failure) for failure in [*case.failures, *attempt_failures])


def _time_based(failure: Failure) -> bool:
    """True when the failure's code, or an upstream code it carries, is in TIME_BASED_CODES.

    WHY the nested shape: the shared marking room keeps the upstream error under
    ``metadata["source_error"]`` (its ``code``, and ``source_code`` for a folded url4 code); only
    the grading stage writes ``source_code`` at the top level of the metadata.
    """
    source_error = failure.metadata.get("source_error")
    nested: Mapping[str, Any] = source_error if isinstance(source_error, Mapping) else {}
    codes = (
        failure.code,
        failure.metadata.get("source_code"),
        nested.get("code"),
        nested.get("source_code"),
    )
    return any(isinstance(code, str) and code in TIME_BASED_CODES for code in codes)
