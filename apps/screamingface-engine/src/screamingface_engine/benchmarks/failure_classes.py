"""Class helpers for the declared failure vocabulary (OME-1234).

Think of the vocabulary as a triage form: when a run dies, the raise site ticks
ONE box — the kind of thing that went wrong — instead of writing the same
catch-all word every time. Each helper here is one box: it fixes the public
``code`` (from ``DECLARED_FAILURE_CODES``) and the retry advice, and the caller
supplies only the human message.

Stage 1 — a raise site picks the helper matching its situation (a malformed
payload, an author mistake, a grader that failed) and raises the returned
``ResolutionError``; ``benchmark_unavailable`` (in ``evaluation.py``) stays the
box for genuinely missing/unreadable assets. Stage 2 — the error travels
upstream and ``aggregation.public_error`` projects code + message + retryable
into the published ``Failure``. Stage 3 — a later PR closes ``Failure.code``
over the declared list, so an undeclared code fails loudly in CI instead of
reaching a researcher.

Worked example: the ensemble runtime receives a selection payload missing its
``tie`` key → ``raise benchmark_contract_error("corrective selection payload
must carry exactly round and tie")`` → the report shows
``grading · benchmark_contract_error — corrective selection payload …``,
retryable false — the researcher fixes the recipe instead of paying to re-run.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.contract import DECLARED_FAILURE_CODES
from url4.core.errors import ResolutionError

# WHY (owner decision, OME-1234): unknown upstream codes map to this class with the
# original spelling preserved in metadata — routine gateway churn must never crash a
# paid run with a ValidationError mid-flight.
UPSTREAM_FALLBACK_CODE = "upstream_error"


def benchmark_contract_error(detail: str) -> ResolutionError:
    """The failure for a payload that violates the benchmark's protocol contract.

    Permanent: the same malformed envelope would arrive again on retry.
    """
    return ResolutionError(detail, code="benchmark_contract_error", permanent=True)


def benchmark_definition_error(detail: str) -> ResolutionError:
    """The failure for a benchmark-author mistake (bad config, impossible selection).

    Permanent: the researcher cannot fix the benchmark's own definition by retrying.
    """
    return ResolutionError(detail, code="benchmark_definition_error", permanent=True)


def judge_failure(detail: str) -> ResolutionError:
    """The failure for a grading judge that could not produce a usable verdict.

    WHY retryable: a grader that ran dry (token cap, empty reply) can succeed on a
    re-resolve — the same deliberate choice gdpval/runtime.py and healthbench/runtime.py
    already made. WHY this code: ``judge_reply_invalid`` is the reconciled spelling
    (owner decision) replacing DRACO's ``no_valid_judge_verdict`` and rubric_check's
    unnamed path — one idea, one code.
    """
    return ResolutionError(detail, code="judge_reply_invalid", permanent=False)


# INVARIANT: a helper can never mint an undeclared code — checked at import time so a
# typo here dies on the first test run, not in a report.
for _helper in (benchmark_contract_error, benchmark_definition_error, judge_failure):
    _code: str = _helper("x").code
    if _code not in DECLARED_FAILURE_CODES:
        raise AssertionError(f"failure class helper mints undeclared code {_code!r}")
if UPSTREAM_FALLBACK_CODE not in DECLARED_FAILURE_CODES:
    raise AssertionError("upstream fallback code is not declared")

__all__ = [
    "UPSTREAM_FALLBACK_CODE",
    "benchmark_contract_error",
    "benchmark_definition_error",
    "judge_failure",
]
