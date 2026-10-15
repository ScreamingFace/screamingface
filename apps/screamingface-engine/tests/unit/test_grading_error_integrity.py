"""Grading failures reach the Case Result as the ORIGINAL upstream error (OME-924).

Before this fix, a failed judge branch inside a Benchmark's inner model-grading fan-out
was collected (url4's default ``on_error="collect"``) into the criterion/rubric row list,
where the case-evaluation route decoded the error object as a typed grading record and
masked the real failure with "invalid Criterion envelope". The repair had two halves:

- the inner fan-out of a judged hand-built Benchmark failed fast, so the original error
  propagated to the shared ``preserve_candidate_outcome()`` boundary. That half and its
  end-to-end judge tests (a judge 429, a judge transport error) went with the last judged
  hand-built Benchmark, HealthBench, when OME-1527 moved it to a local inspect Task (DRACO
  before it); a local Task's judge failure is the scorer adapter's, pinned in the inspect lane;
- url4's collect payload carries the exception's own ``code`` and ``retryable`` beside
  kind/message, so ``public_error`` renders the upstream failure instead of the default.
  That half is the shared aggregation's and is pinned below, on MedXpertQA, the last
  hand-built Benchmark.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.graded_answer import graded_answer_payload
from screamingface_engine.benchmarks.medxpert import aggregate as medxpert_agg

pytestmark = pytest.mark.asyncio

# --- the aggregate renders the original error, not an envelope failure ------------------


def _execution(case_id: int, answer: str, grading: object) -> dict[str, object]:
    return graded_answer_payload(
        case_id,
        encode_candidate_invocation(answer, "stop", None),
        [grading],
    )


def _error_row(
    *,
    kind: str = "ResolutionError",
    code: str | None = None,
    message: str = "upstream judge rate limited",
    retryable: bool | None = None,
    permanent: bool | None = None,
) -> dict[str, object]:
    error: dict[str, object] = {"kind": kind, "message": message}
    if code is not None:
        error["code"] = code
    if retryable is not None:
        error["retryable"] = retryable
    if permanent is not None:
        error["permanent"] = permanent
    return {"error": error}


def _write_medxpert_case(root: Path) -> None:
    (root / "answers").mkdir(parents=True, exist_ok=True)
    (root / "cases.json").write_text(json.dumps([{"id": 1, "input": "input-1"}]), encoding="utf-8")
    (root / "answers" / "1.json").write_text(json.dumps({"label": "C"}), encoding="utf-8")


async def test_a_grading_error_preserves_code_and_retryable(tmp_path: Path) -> None:
    _write_medxpert_case(tmp_path)
    rows = json.dumps(
        [
            _execution(
                1,
                "the candidate answer",
                _error_row(code="rate_limited", retryable=True),
            )
        ]
    )
    result = medxpert_agg.aggregate(
        rows,
        tmp_path,
        benchmark_id="medxpert-test",
        benchmark_revision="revision",
        case_ids=(1,),
    )

    (case,) = result["cases"]
    assert case["status"] == "failed"
    assert case["output"] == "the candidate answer"
    assert case["grade"]["score"] is None
    (failure,) = case["failures"]
    assert failure["stage"] == "grading"
    assert failure["code"] == "rate_limited"
    assert failure["retryable"] is True
    assert failure["metadata"] == {"error_kind": "ResolutionError"}


def _medxpert_failure(tmp_path: Path, grading: object) -> dict[str, object]:
    """Aggregate one MedXpertQA Case whose grading collected ``grading``; its one Failure."""

    _write_medxpert_case(tmp_path)
    result = medxpert_agg.aggregate(
        json.dumps([_execution(1, "the candidate answer", grading)]),
        tmp_path,
        benchmark_id="medxpert-test",
        benchmark_revision="revision",
        case_ids=(1,),
    )
    (case,) = result["cases"]
    (failure,) = case["failures"]
    return failure


async def test_a_grading_failure_keeps_a_permanent_classification(tmp_path: Path) -> None:
    # Moved from DRACO's aggregate, then HealthBench's (OME-1527): the same shared
    # `public_error` rendering.
    failure = _medxpert_failure(tmp_path, _error_row(code="aigateway_bad_response", permanent=True))

    assert failure["code"] == "aigateway_bad_response"
    assert failure["retryable"] is False


async def test_a_grading_failure_without_code_falls_back_to_the_default(tmp_path: Path) -> None:
    # A legacy collect payload (kind + message only) still renders, with the benchmark's
    # declared default code — backward compatible with pre-OME-924 error cases.
    failure = _medxpert_failure(tmp_path, _error_row())

    assert failure["stage"] == "grading"
    assert failure["code"] == "medxpert_grading_failed"
    assert failure["retryable"] is None
    assert failure["message"] == "upstream judge rate limited"
