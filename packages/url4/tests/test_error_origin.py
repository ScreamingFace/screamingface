"""Explicit diagnostic origin survives collection without changing unmarked errors."""

import pytest

from url4.core.errors import ResolutionError
from url4.dag.nodes._shared import _error_payload


def test_marked_error_preserves_code_message_and_retryability():
    error = ResolutionError(
        "unavailable", code="precise_code", permanent=False, origin="some_boundary"
    )
    assert _error_payload(error) == {
        "error": {
            "kind": "ResolutionError",
            "message": "unavailable",
            "code": "precise_code",
            "retryable": True,
            "origin": "some_boundary",
        }
    }


def test_unmarked_error_retains_old_wire_shape():
    error = ResolutionError("failure", code="code", permanent=True)
    assert error.origin is None
    assert _error_payload(error) == {
        "error": {
            "kind": "ResolutionError",
            "message": "failure",
            "code": "code",
            "retryable": False,
        }
    }


@pytest.mark.parametrize("origin", ["", "x" * 65, "has space", "a\nb", "É", True, 4, "Upper"])
def test_invalid_origin_is_rejected(origin):
    with pytest.raises(ValueError):
        ResolutionError("failure", origin=origin)


def test_maximum_origin_length():
    assert (
        _error_payload(ResolutionError("failure", origin="x" * 64))["error"]["origin"] == "x" * 64
    )


@pytest.mark.asyncio
async def test_real_iteration_carries_origin_without_changing_successful_siblings():
    import json

    from url4.core.nodes import Iteration, Url
    from url4.dag import ExecutionContext, run
    from url4.io.static import StaticIOLayer

    def resolve(context: str, intent: str) -> str:
        if "fail" in context:
            raise ResolutionError("unavailable", code="provider_unavailable", origin="model_call")
        return "answer"

    io = StaticIOLayer(
        fetch_map={"https://cases": json.dumps([{"q": "fail"}, {"q": "ok"}])},
        routes={"/solve": resolve},
    )
    result = await run(
        Iteration(collection=Url("https://cases"), body="/solve($item.q)!answer"),
        ctx=ExecutionContext(io, strict_fields=True),
    )
    failed, succeeded = json.loads(result)
    assert failed["error"]["origin"] == "model_call"
    assert failed["error"]["code"] == "provider_unavailable"
    assert succeeded == "answer"
