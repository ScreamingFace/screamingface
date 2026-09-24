"""OME-1197: provenance, not rewritten diagnostic codes, attributes failures."""

import httpx
import pytest
from test_ifeval_provider_failure_stage import _aggregate, _collect_candidate_error

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.world.connector import _raise_for_status
from url4.core.errors import ResolutionError
from url4.dag.nodes._shared import _error_payload


@pytest.mark.parametrize(
    "status,code",
    [(503, "provider_unavailable"), (401, "auth_required"), (404, "profile_not_found")],
)
@pytest.mark.asyncio
async def test_rewritten_gateway_code_retains_candidate_origin(status, code):
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(
            httpx.Response(status, json={"detail": {"code": code, "message": "safe failure"}})
        )
    error = await _collect_candidate_error(caught.value)
    assert error["error"]["kind"] == "CandidateExecutionError"
    assert "origin" not in error["error"]
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


@pytest.mark.asyncio
async def test_protected_checker_wins_over_inner_model_call_origin():
    row = case_execution_payload(
        153,
        encode_candidate_invocation("answer", "stop", None),
        [
            await _collect_candidate_error(
                ResolutionError("judge unavailable", code="provider_unavailable")
            )
        ],
    )
    assert _aggregate(row)["cases"][0]["failures"][0]["stage"] == "grading"


@pytest.mark.asyncio
async def test_candidate_scope_failure_preserves_diagnostics():
    from url4.core.errors import ScopeError

    row = await _collect_candidate_error(ScopeError("missing input"))
    assert row["error"] == {
        "kind": "CandidateExecutionError",
        "message": "missing input",
        "code": "unbound_reference",
        "retryable": False,
    }
    assert _aggregate(row)["cases"][0]["failures"][0]["stage"] == "candidate"


@pytest.mark.asyncio
async def test_unexpected_exception_is_not_marked_candidate():
    row = await _collect_candidate_error(RuntimeError("implementation bug"))
    assert row["error"]["kind"] == "RuntimeError"
    assert _aggregate(row)["cases"][0]["failures"][0]["stage"] == "grading"


@pytest.mark.asyncio
async def test_cancellation_is_not_collected_as_candidate_failure():
    import asyncio

    with pytest.raises(asyncio.CancelledError):
        await _collect_candidate_error(asyncio.CancelledError())


@pytest.mark.asyncio
async def test_candidate_failure_preserves_successful_sibling():
    import json

    from screamingface_engine.benchmarks.contract import decode_candidate_invocation
    from screamingface_engine.world.candidate_adapter import install_candidate_invocation
    from url4 import RelExpr, expr, iterate, render, src, text
    from url4.peer.server import Url4Node

    node = Url4Node("mixed-candidate-results")
    node.endpoint("/passthrough")(lambda request: request.intent)
    install_candidate_invocation(node)

    @node.endpoint("/answer")
    def answer(request):
        if request.context == "fail":
            raise ResolutionError("unavailable", code="provider_unavailable")
        return "original answer"

    call = RelExpr(
        path="/benchmarks/candidate",
        context="$item",
        intent=text(
            render(
                expr(
                    src(
                        RelExpr(path="/answer", context="$input", intent=text("answer")),
                        name="value",
                        weight=0.0,
                    ),
                    intent=text("$value"),
                )
            )
        ),
        params=(("web_search", "false"),),
    )
    result = await node.evaluate(
        render(
            iterate(
                [text("fail"), text("ok")],
                body=src(call, name="result", weight=0.0),
                intent=text("$result"),
            )
        )
    )
    failed, succeeded = json.loads(result.text)
    assert failed["error"]["kind"] == "CandidateExecutionError"
    assert decode_candidate_invocation(json.dumps(succeeded))[0] == "original answer"
