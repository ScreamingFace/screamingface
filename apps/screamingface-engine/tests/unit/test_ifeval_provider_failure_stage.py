"""OME-981: connector diagnostics retain Candidate provenance through collection."""

from __future__ import annotations

import json

import httpx
import pytest

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.ifeval.grade import AggregateError, aggregate
from screamingface_engine.runner.connector import _raise_for_status
from url4.core.errors import ResolutionError
from url4.dag.nodes import _error_payload

_SPEC = {
    153: {
        "prompt": "Answer without commas.",
        "instruction_id_list": ["punctuation:no_comma"],
        "kwargs": [{}],
    }
}


def _aggregate(row: dict):
    return aggregate(json.dumps([row]), _SPEC, "ifeval", [153], selected_case_count=1)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503, 599])
def test_connector_http_error_survives_collection_as_candidate_failure(status: int) -> None:
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(httpx.Response(status))
    result = _aggregate(_error_payload(caught.value))
    case = result["cases"][0]
    failure = case["failures"][0]
    assert failure == {
        "stage": "candidate",
        "code": f"aigateway_http_{status}",
        "message": f"aigateway request failed with status {status}",
        "retryable": status == 429 or status >= 500,
        "case_id": 153,
        "metadata": {"row_index": 0, "error_kind": "ResolutionError"},
    }
    assert case["status"] == "failed"
    assert case["grade"] is None
    assert result["score"] is None
    assert result["coverage"] == 0.0
    assert result["case_count"] == 1


@pytest.mark.parametrize(
    "code", ["aigateway_transport_error", "aigateway_empty_response", "aigateway_bad_response"]
)
def test_known_connector_failures_are_candidate_stage(code: str) -> None:
    result = _aggregate(
        _error_payload(ResolutionError("Model call failed", code=code, permanent=False))
    )
    failure = result["cases"][0]["failures"][0]
    assert (failure["stage"], failure["code"], failure["retryable"]) == ("candidate", code, True)


@pytest.mark.parametrize(
    "code",
    [
        None,
        "provider_error",
        "aigateway_unknown",
        "aigateway_http_200",
        "aigateway_http_600",
        "aigateway_http_503_suffix",
        " aigateway_http_503",
        503,
    ],
)
def test_ambiguous_errors_do_not_gain_candidate_provenance(code: object) -> None:
    # INVARIANT: messages and a broad provider prefix are not attribution evidence.
    result = _aggregate(
        {
            "error": {
                "kind": "ResolutionError",
                "code": code,
                "message": "aigateway request failed with status 503",
            }
        }
    )
    assert result["cases"][0]["failures"][0]["stage"] == "grading"


@pytest.mark.parametrize("code", ["ifeval_checker_failed", "aigateway_http_503"])
def test_protected_checker_failure_keeps_its_grading_boundary(code: str) -> None:
    row = case_execution_payload(
        153,
        encode_candidate_invocation("Answer", "stop", None),
        [_error_payload(ResolutionError("Checker failed", code=code, permanent=False))],
    )
    case = _aggregate(row)["cases"][0]
    assert case["output"] == "Answer"
    assert case["failures"][0]["stage"] == "grading"


def test_malformed_evaluation_is_not_an_operational_failure() -> None:
    with pytest.raises(AggregateError, match="position 0"):
        _aggregate({"candidate_text": "aigateway_http_503"})
