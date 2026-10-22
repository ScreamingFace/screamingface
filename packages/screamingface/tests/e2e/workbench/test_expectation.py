"""The expected-failure verdict (spec §3.7; unit 7 plan, Task 1), as pure functions.

Every red case of the plan is here: unexpected pass, wrong code, wrong stage, missing evidence
(no report) and no error telemetry — plus a malformed declaration, which is red, never ignored.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from workbench.expectation import Expectation, judge_expectation, parse_expect

_DECLARED = {"outcome": "fail", "failure_codes": ["provider_error"], "stage": "candidate"}


def _failure(code: str, stage: str = "candidate") -> dict[str, Any]:
    return {"stage": stage, "code": code, "message": "m", "retryable": None, "metadata": {}}


def _report(*failures: dict[str, Any], where: str = "case") -> dict[str, Any]:
    """A report.v1 shape with the failures on a case (or on the candidate)."""
    case = {"status": "failed", "case_id": 1, "failures": list(failures)}
    candidate = {"name": "fusion", "cases": [case], "failures": [], "members": []}
    if where == "candidate":
        candidate["failures"], case["failures"] = list(failures), []
    return {"schema": "screamingface.report.v1", "candidates": [candidate]}


def _events(*rows: dict[str, Any]) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


_ERROR_SPAN = {"kind": "span", "status": "error", "refusal": None, "name": "chat"}
_OK_SPAN = {"kind": "span", "status": "ok", "refusal": None, "name": "chat"}
_ERROR_LOG = {"kind": "log", "severity_number": 17, "severity_text": "ERROR", "body": "x"}
_INFO_LOG = {"kind": "log", "severity_number": 9, "severity_text": "INFO", "body": "x"}


def _judge(report: dict[str, Any] | None, events: str) -> tuple[list[str], dict[str, Any]]:
    expect, problems = parse_expect(_DECLARED)
    assert expect is not None and problems == []
    return judge_expectation(expect, report, events)


def test_the_declared_failure_with_error_telemetry_holds() -> None:
    reasons, observed = _judge(_report(_failure("provider_error")), _events(_ERROR_SPAN))
    assert reasons == []
    assert observed["failures"] == [{"code": "provider_error", "stage": "candidate"}]
    assert observed["error_telemetry"] == {"spans": 1, "logs": 0}


def test_a_candidate_level_failure_counts_too() -> None:
    reasons, _ = _judge(_report(_failure("provider_error"), where="candidate"), _events(_ERROR_LOG))
    assert reasons == []


def test_an_error_log_alone_is_error_telemetry() -> None:
    reasons, observed = _judge(_report(_failure("provider_error")), _events(_INFO_LOG, _ERROR_LOG))
    assert reasons == [] and observed["error_telemetry"] == {"spans": 0, "logs": 1}


def test_a_refused_span_is_error_telemetry() -> None:
    refused = _OK_SPAN | {"refusal": "model refused"}
    reasons, _ = _judge(_report(_failure("provider_error")), _events(refused))
    assert reasons == []


# Review Focus 1: a re-blessed tape makes the model servable → red, never green.
def test_an_unexpected_pass_is_red() -> None:
    reasons, observed = _judge(_report(), _events(_ERROR_SPAN))
    assert observed["failures"] == []
    (reason,) = reasons
    assert reason.startswith("unexpected pass:")
    assert "provider_error" in reason and "candidate" in reason


# Review Focus 2: a changed code names the old and the new.
def test_a_different_failure_code_is_red_and_names_both_codes() -> None:
    reasons, _ = _judge(_report(_failure("aigateway_http_404")), _events(_ERROR_SPAN))
    (reason,) = reasons
    assert reason.startswith("wrong failure code:")
    assert "expected ['provider_error']" in reason
    assert "observed ['aigateway_http_404']" in reason


def test_an_extra_undeclared_code_beside_the_declared_one_is_red() -> None:
    report = _report(_failure("provider_error"), _failure("grading_failed", "grading"))
    reasons, _ = _judge(report, _events(_ERROR_SPAN))
    (reason,) = reasons
    assert reason.startswith("wrong failure code:") and "grading_failed" in reason


def test_the_declared_code_at_another_stage_is_red() -> None:
    reasons, _ = _judge(_report(_failure("provider_error", "grading")), _events(_ERROR_SPAN))
    (reason,) = reasons
    assert reason == (
        "wrong failure stage for 'provider_error': expected 'candidate', observed ['grading']"
    )


def test_a_missing_report_is_missing_evidence() -> None:
    reasons, observed = _judge(None, _events(_ERROR_SPAN))
    (reason,) = reasons
    assert reason.startswith("missing evidence: no report.json")
    assert observed["failures"] is None


def test_no_error_telemetry_is_red() -> None:
    reasons, observed = _judge(_report(_failure("provider_error")), _events(_OK_SPAN, _INFO_LOG))
    (reason,) = reasons
    assert reason.startswith("no error telemetry:")
    assert observed["error_telemetry"] == {"spans": 0, "logs": 0}


def test_no_events_at_all_is_no_error_telemetry() -> None:
    reasons, _ = _judge(_report(_failure("provider_error")), "")
    assert [r.split(":")[0] for r in reasons] == ["no error telemetry"]


def test_a_torn_or_foreign_events_line_is_skipped_not_fatal() -> None:
    text = '{"kind": "span", "status": "err' + "\n" + "[1, 2]\n" + _events(_ERROR_LOG)
    reasons, observed = _judge(_report(_failure("provider_error")), text)
    assert reasons == [] and observed["error_telemetry"] == {"spans": 0, "logs": 1}


def test_parse_accepts_the_declared_shape() -> None:
    expect, problems = parse_expect(_DECLARED)
    assert problems == [] and expect is not None
    assert expect == Expectation(failure_codes=("provider_error",), stage="candidate")
    assert expect.to_json() == _DECLARED


@pytest.mark.parametrize(
    "raw",
    [
        "fail",
        {"outcome": "pass", "failure_codes": ["provider_error"], "stage": "candidate"},
        {"outcome": "fail", "failure_codes": [], "stage": "candidate"},
        {"outcome": "fail", "failure_codes": "provider_error", "stage": "candidate"},
        {"outcome": "fail", "failure_codes": ["not_a_declared_code"], "stage": "candidate"},
        {"outcome": "fail", "failure_codes": ["provider_error"], "stage": "nowhere"},
        {"outcome": "fail", "failure_codes": ["provider_error"]},
    ],
)
def test_a_malformed_declaration_is_red_never_ignored(raw: object) -> None:
    expect, problems = parse_expect(raw)
    assert expect is None
    assert problems and all(p.startswith("malformed workbench.expect") for p in problems)
