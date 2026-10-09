"""The receiver side of an RDS code-pointer call: `dispatch`, `dispatch_direct` and the ASGI shim.

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author, a URI intent runs one registered handler with the group's sources as a
# structured JSON document, and an LLM call on the same node keeps its meaning.
#
# INVARIANT: an RDS request is never evaluated and never served as data. A path with no endpoint
# fails with `intent_error`, so a data route cannot be read as instructions (E2).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
import pytest

from url4.core.errors import ErrorCode, ParseError, ResolutionError, Url4Error
from url4.peer import DirectResult, dispatch_direct
from url4.peer.server import EndpointHandler, Request, Url4Node
from url4.wire.rds import RdsValue, encode_rds_document, encode_rds_target
from url4.wire.subrequest import split_expression_query

_INPUTS: dict[str, RdsValue] = {
    "member_1": 'A (says) 4 & 5%+\n"q" é',
    "extract_pattern": "ANSWER: \\d+",
}
_DOC = encode_rds_document(_INPUTS)


def _node_with(handler: EndpointHandler) -> Url4Node:
    node = Url4Node("t")
    node.endpoint("/combine")(handler)
    return node


def _recording_node() -> tuple[Url4Node, list[Request]]:
    seen: list[Request] = []

    async def combine(request: Request) -> str:
        seen.append(request)
        return "combined"

    return _node_with(combine), seen


def _http(node: Url4Node) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=node.asgi())
    return httpx.AsyncClient(transport=transport, base_url="http://t")


def test_split_expression_query_returns_raw_values_without_validating_them() -> None:
    params, q = split_expression_query("tone=a@b&flag&limit=1%2C2&q=(x)!go")
    assert params == [("tone", "a@b"), ("flag", None), ("limit", "1%2C2")]
    assert q == "(x)!go"


@pytest.mark.asyncio
async def test_a_raw_rds_target_reaches_the_handler_with_every_field() -> None:
    """Row 10: the raw wire convention (url4's own writer) decodes to the same document."""
    node, seen = _recording_node()
    target = encode_rds_target("/combine", "reducer=vote&extract=last_number@1", _DOC)
    assert await node.fetch(target, relative=True) == "combined"
    (request,) = seen
    assert request.path == "/combine"
    assert request.mode == "rds"
    assert request.intent == ""
    assert request.context == _DOC
    assert request.params == {"reducer": "vote", "extract": "last_number@1"}
    assert request.inputs == _INPUTS


@pytest.mark.asyncio
async def test_a_fully_encoded_rds_target_reaches_the_handler_with_every_field() -> None:
    """Row 10: a standard HTTP client escapes every paren, and the document decodes the same."""
    node, seen = _recording_node()
    target = f"/combine?reducer=vote&extract=last_number@1&q={quote('(' + _DOC + ')', safe='')}"
    assert await node.fetch(target, relative=True) == "combined"
    (request,) = seen
    assert request.mode == "rds"
    assert request.intent == ""
    assert request.context == _DOC
    assert request.params == {"reducer": "vote", "extract": "last_number@1"}
    assert request.inputs == _INPUTS


@pytest.mark.asyncio
async def test_an_at_sign_in_a_query_tail_param_is_kept_for_an_rds_call() -> None:
    node, seen = _recording_node()
    await node.fetch(encode_rds_target("/combine", "extract=last_number@1", _DOC), relative=True)
    assert seen[0].params == {"extract": "last_number@1"}


@pytest.mark.parametrize(
    ("query", "context", "intent"),
    [
        ("q=(ctx)!intent", "ctx", "intent"),
        ("q=()!x", "", "x"),
        ("q=(plain-text)", "plain-text", ""),
        ("q=" + quote("(ctx)!intent", safe=""), "ctx", "intent"),
    ],
)
@pytest.mark.asyncio
async def test_an_llm_call_shape_reaches_the_handler_in_llm_mode(
    query: str, context: str, intent: str
) -> None:
    """Row 11: every LLM shape keeps mode "llm" and no inputs, including the fully-encoded form."""
    node, seen = _recording_node()
    await node.fetch(f"/combine?{query}", relative=True)
    (request,) = seen
    assert request.mode == "llm"
    assert request.inputs is None
    assert request.context == context
    assert request.intent == intent


@pytest.mark.asyncio
async def test_an_at_sign_in_a_protocol_param_is_refused_for_an_llm_call() -> None:
    """E9: an LLM endpoint call still validates its params with `param-value`."""
    node, _ = _recording_node()
    with pytest.raises(ParseError) as exc:
        await node.fetch("/combine?tone=a@b&q=(ctx)!intent", relative=True)
    assert exc.value.code == ErrorCode.MALFORMED_SOURCE


@pytest.mark.asyncio
async def test_an_rds_call_to_a_data_route_only_path_is_intent_error() -> None:
    """E2: a data route is never read as a code pointer."""
    node = Url4Node("t")
    node.data("/api/rows", '["alpha"]')
    with pytest.raises(ResolutionError) as exc:
        await node.fetch(encode_rds_target("/api/rows", "", _DOC), relative=True)
    assert exc.value.code == ErrorCode.INTENT_ERROR
    assert exc.value.permanent is True


@pytest.mark.asyncio
async def test_an_rds_call_to_a_missing_path_is_intent_error() -> None:
    """E1: an unknown code pointer fails with intent_error, permanently."""
    node = Url4Node("t")
    with pytest.raises(ResolutionError) as exc:
        await node.fetch(encode_rds_target("/nope", "", _DOC), relative=True)
    assert exc.value.code == ErrorCode.INTENT_ERROR
    assert exc.value.permanent is True
    assert "/nope" in str(exc.value)


@pytest.mark.asyncio
async def test_an_rds_call_to_the_eval_path_is_intent_error_and_never_evaluates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node, _ = _recording_node()
    evaluated: list[object] = []

    async def evaluate(*args: object, **kwargs: object) -> str:
        evaluated.append(args)
        return "evaluated"

    monkeypatch.setattr(node, "_run_text", evaluate)
    with pytest.raises(ResolutionError) as exc:
        await node.fetch(encode_rds_target("/v1", "", _DOC), relative=True)
    assert exc.value.code == ErrorCode.INTENT_ERROR
    assert evaluated == []


@pytest.mark.asyncio
async def test_a_code_pointer_that_raises_value_error_is_intent_error_permanent() -> None:
    """E3: a non-url4 exception from a handler becomes intent_error."""

    async def combine(request: Request) -> str:
        raise ValueError("bad input")

    with pytest.raises(ResolutionError) as exc:
        await _node_with(combine).fetch(encode_rds_target("/combine", "", _DOC), relative=True)
    assert exc.value.code == ErrorCode.INTENT_ERROR
    assert exc.value.permanent is True


@pytest.mark.asyncio
async def test_a_code_pointer_that_returns_a_non_text_result_is_intent_error() -> None:
    """A handler result must be text; anything else fails with intent_error."""

    async def combine(request: Request) -> Any:
        return 42

    with pytest.raises(ResolutionError) as exc:
        await _node_with(combine).fetch(encode_rds_target("/combine", "", _DOC), relative=True)
    assert exc.value.code == ErrorCode.INTENT_ERROR
    assert exc.value.permanent is True


@pytest.mark.asyncio
async def test_a_code_pointer_url4_error_keeps_its_code_and_permanence() -> None:
    """E3: a Url4Error the handler raises is re-raised with its own code and permanence."""

    async def combine(request: Request) -> str:
        raise Url4Error("x", code="x.custom", permanent=False)

    with pytest.raises(Url4Error) as exc:
        await _node_with(combine).fetch(encode_rds_target("/combine", "", _DOC), relative=True)
    assert exc.value.code == "x.custom"
    assert exc.value.permanent is False


@pytest.mark.asyncio
async def test_a_duplicate_query_tail_key_in_an_rds_call_is_malformed_source() -> None:
    node, seen = _recording_node()
    target = encode_rds_target("/combine", "a=1&a=2", _DOC)
    with pytest.raises(ParseError) as exc:
        await node.fetch(target, relative=True)
    assert exc.value.code == ErrorCode.MALFORMED_SOURCE
    assert seen == []


@pytest.mark.asyncio
async def test_an_rds_call_whose_code_pointer_raises_value_error_answers_422() -> None:
    async def combine(request: Request) -> str:
        raise ValueError("bad input")

    async with _http(_node_with(combine)) as http:
        response = await http.get(encode_rds_target("/combine", "", _DOC))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "intent_error"


@pytest.mark.asyncio
async def test_an_rds_call_whose_code_pointer_raises_unsupported_mode_answers_400() -> None:
    async def combine(request: Request) -> str:
        raise Url4Error("no", code=ErrorCode.UNSUPPORTED_MODE, permanent=True)

    async with _http(_node_with(combine)) as http:
        response = await http.get(encode_rds_target("/combine", "", _DOC))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_mode"


@pytest.mark.asyncio
async def test_dispatch_direct_gives_an_rds_target_the_handler_in_rds_mode() -> None:
    node, seen = _recording_node()
    result = await dispatch_direct(node, encode_rds_target("/combine", "", _DOC))
    assert result == DirectResult(body="combined", media_type=None)
    assert seen[0].mode == "rds"
    assert seen[0].inputs == _INPUTS


@pytest.mark.asyncio
async def test_dispatch_direct_rds_call_to_a_missing_path_is_intent_error() -> None:
    with pytest.raises(ResolutionError) as exc:
        await dispatch_direct(Url4Node("t"), encode_rds_target("/nope", "", _DOC))
    assert exc.value.code == ErrorCode.INTENT_ERROR
    assert exc.value.permanent is True


@pytest.mark.asyncio
async def test_an_rds_call_whose_code_pointer_raises_value_error_does_not_echo_its_detail() -> None:
    """SF7: the 422 body names the exception type, never the handler's message text."""

    async def combine(request: Request) -> str:
        raise ValueError("secret-detail")

    async with _http(_node_with(combine)) as http:
        response = await http.get(encode_rds_target("/combine", "", _DOC))
    assert response.status_code == 422
    assert "secret-detail" not in response.text
    assert "ValueError" in response.json()["error"]["message"]
