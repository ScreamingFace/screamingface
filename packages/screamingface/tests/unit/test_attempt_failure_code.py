"""The SDK accepts the Attempts fold's failure code in a Report Failure (OME-1458)."""

from __future__ import annotations

from screamingface._report_primitives import Failure, is_declared_failure_code


def test_attempt_grade_not_pass_fail_is_a_declared_code() -> None:
    # WHY: the Engine fails a Case by this name when an Attempt's Check is graded neither
    # 0 nor 1, so any-match has no meaning; a consumer refusing the code would fail to
    # load a valid report.
    assert is_declared_failure_code("attempt_grade_not_pass_fail")
    failure = Failure(stage="grading", code="attempt_grade_not_pass_fail", message="m")
    assert failure.code == "attempt_grade_not_pass_fail"
