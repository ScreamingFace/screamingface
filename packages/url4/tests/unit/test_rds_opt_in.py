"""An endpoint receives code-pointer calls only when it opts in with ``rds=True`` (ans:Q7).

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author, a model route I register for prompts never receives a JSON document of
# my group's sources, because only the endpoints I mark as code pointers run code.
#
# INVARIANT: a handler written for prompts never sees a code-pointer call. The refusal happens
# before the handler runs, and an LLM call to the same endpoint is still delivered.
"""

from __future__ import annotations

import httpx
import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.peer import dispatch_direct
from url4.peer.server import Request, Url4Node
from url4.wire.rds import RdsValue, encode_rds_document, encode_rds_target

_INPUTS: dict[str, RdsValue] = {"a": "1", "b": "2"}
_DOC = encode_rds_document(_INPUTS)


def _node(*, rds: bool) -> tuple[Url4Node, list[Request]]:
    seen: list[Request] = []

    async def model(request: Request) -> str:
        seen.append(request)
        return "answered"

    node = Url4Node("t")
    node.endpoint("/model", rds=rds)(model)
    return node, seen


def _http(node: Url4Node) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=node.asgi())
    return httpx.AsyncClient(transport=transport, base_url="http://t")


@pytest.mark.asyncio
async def test_fetch_refuses_a_code_pointer_without_the_flag() -> None:
    """The handler never runs; the caller gets a permanent intent_error."""
    node, seen = _node(rds=False)
    with pytest.raises(ResolutionError) as exc:
        await node.fetch(encode_rds_target("/model", "", _DOC), relative=True)
    assert exc.value.code == ErrorCode.INTENT_ERROR
    assert exc.value.permanent is True
    assert "does not take code-pointer calls" in str(exc.value)
    assert seen == []


@pytest.mark.asyncio
async def test_dispatch_direct_refuses_a_code_pointer_without_the_flag() -> None:
    node, seen = _node(rds=False)
    with pytest.raises(ResolutionError) as exc:
        await dispatch_direct(node, encode_rds_target("/model", "", _DOC))
    assert exc.value.code == ErrorCode.INTENT_ERROR
    assert exc.value.permanent is True
    assert seen == []


@pytest.mark.asyncio
async def test_http_answers_422_for_a_code_pointer_without_the_flag() -> None:
    node, seen = _node(rds=False)
    async with _http(node) as client:
        response = await client.get(encode_rds_target("/model", "", _DOC))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.INTENT_ERROR
    assert seen == []


@pytest.mark.asyncio
async def test_an_expression_code_pointer_without_the_flag_is_refused() -> None:
    """The expression `(a='1')!/model` is a code-pointer call too, so it is refused the same way."""
    node, seen = _node(rds=False)
    with pytest.raises(ResolutionError) as exc:
        await node.evaluate("(a='1')!/model")
    assert exc.value.code == ErrorCode.INTENT_ERROR
    assert exc.value.permanent is True
    assert seen == []


@pytest.mark.asyncio
async def test_an_llm_call_with_the_flag_still_reaches_the_handler() -> None:
    """A prompt call is delivered whether or not the endpoint opts in; here it does."""
    node, seen = _node(rds=True)
    assert await node.fetch("/model?q=(ctx)!go", relative=True) == "answered"
    (request,) = seen
    assert request.mode == "llm"
    assert request.inputs is None
    assert request.context == "ctx"
    assert request.intent == "go"


@pytest.mark.asyncio
async def test_a_code_pointer_with_the_flag_reaches_the_handler() -> None:
    node, seen = _node(rds=True)
    assert await node.fetch(encode_rds_target("/model", "", _DOC), relative=True) == "answered"
    (request,) = seen
    assert request.mode == "rds"
    assert request.intent == ""
    assert request.context == _DOC
    assert request.inputs == _INPUTS
