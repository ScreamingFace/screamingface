"""OME-981: connector diagnostics retain Candidate provenance through collection."""

from __future__ import annotations

import json

import httpx
import pytest

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.ifeval.grade import AggregateError, aggregate
from screamingface_engine.world import connector
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.connector import _raise_for_status
from url4 import RelExpr, expr, iterate, render, src, text
from url4.core.errors import ResolutionError
from url4.dag.nodes._shared import _error_payload
from url4.peer.server import Url4Node

_SPEC = {
    153: {
        "prompt": "Answer without commas.",
        "instruction_id_list": ["punctuation:no_comma"],
        "kwargs": [{}],
    }
}


def _aggregate(row: dict):
    return aggregate(json.dumps([row]), _SPEC, "ifeval", [153], selected_case_count=1)


async def _collect_candidate_error(error: BaseException) -> dict:
    """Exercise the actual candidate boundary and URL4 collect serialization."""
    node = Url4Node("candidate-failure-test")
    node.endpoint("/passthrough")(lambda request: request.intent)
    install_candidate_invocation(node)

    @node.endpoint("/fail")
    def fail(_request):
        raise error

    call = RelExpr(
        path="/benchmarks/candidate",
        context="question",
        intent=text(
            render(
                expr(
                    src(
                        RelExpr(path="/fail", context="question", intent=text("answer")),
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
                [text("case")], body=src(call, name="result", weight=0.0), intent=text("$result")
            )
        )
    )
    return json.loads(result.text)[0]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503, 599])
@pytest.mark.asyncio
async def test_connector_http_error_survives_collection_as_candidate_failure(status: int) -> None:
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(httpx.Response(status))
    result = _aggregate(await _collect_candidate_error(caught.value))
    case = result["cases"][0]
    failure = case["failures"][0]
    assert failure == {
        "stage": "candidate",
        "code": f"aigateway_http_{status}",
        "message": f"aigateway request failed with status {status}",
        "retryable": status == 429 or status >= 500,
        "case_id": 153,
        "metadata": {"row_index": 0, "error_kind": "CandidateExecutionError"},
    }
    assert case["status"] == "failed"
    assert case["grade"] is None
    assert result["score"] is None
    assert result["coverage"] == 0.0
    assert result["case_count"] == 1


@pytest.mark.parametrize(
    "code", ["aigateway_transport_error", "aigateway_empty_response", "aigateway_bad_response"]
)
@pytest.mark.asyncio
async def test_known_connector_failures_are_candidate_stage(code: str, monkeypatch) -> None:
    # Exercise the actual boundary so origin cannot be fabricated by this fixture.
    with pytest.raises(ResolutionError) as caught:
        if code == "aigateway_transport_error":
            monkeypatch.setattr(connector, "_TRANSPORT_RETRIES", 0)

            def unavailable(request):
                raise httpx.ConnectError("unreachable", request=request)

            async with httpx.AsyncClient(
                base_url="https://gateway.test", transport=httpx.MockTransport(unavailable)
            ) as client:
                await connector._post_completion(client, headers={}, body={})
        else:
            body = b"" if code == "aigateway_empty_response" else b"not JSON"
            connector._json_or_raise(httpx.Response(200, content=body))
    result = _aggregate(await _collect_candidate_error(caught.value))
    failure = result["cases"][0]["failures"][0]
    assert (failure["stage"], failure["code"], failure["retryable"]) == (
        "candidate",
        code,
        code != "aigateway_bad_response",
    )


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
