"""OME-1197: provenance, not rewritten diagnostic codes, attributes failures."""

import httpx
import pytest
from test_ifeval_provider_failure_stage import _aggregate

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.world.connector import _raise_for_status
from url4.core.errors import ResolutionError
from url4.dag.nodes._shared import _error_payload


@pytest.mark.parametrize(
    "status,code",
    [(503, "provider_unavailable"), (401, "auth_required"), (404, "profile_not_found")],
)
def test_rewritten_gateway_code_retains_candidate_origin(status, code):
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(
            httpx.Response(status, json={"detail": {"code": code, "message": "safe failure"}})
        )
    error = _error_payload(caught.value)
    assert error["error"]["origin"] == "model_call"
    failure = _aggregate(error)["cases"][0]["failures"][0]
    assert failure["stage"] == "candidate"
    assert failure["message"] == "safe failure"
    assert failure["metadata"]["source_code"] == code
    assert failure["retryable"] is (status == 503)


@pytest.mark.parametrize(
    "code",
    [
        "aigateway_http_503",
        "aigateway_transport_error",
        "aigateway_empty_response",
        "aigateway_bad_response",
    ],
)
def test_unmarked_code_never_claims_model_origin(code):
    row = _error_payload(ResolutionError("failed", code=code))
    assert _aggregate(row)["cases"][0]["failures"][0]["stage"] == "grading"


def test_protected_checker_wins_over_inner_model_call_origin():
    row = case_execution_payload(
        153,
        encode_candidate_invocation("answer", "stop", None),
        [
            _error_payload(
                ResolutionError(
                    "judge unavailable", code="provider_unavailable", origin="model_call"
                )
            )
        ],
    )
    assert _aggregate(row)["cases"][0]["failures"][0]["stage"] == "grading"
