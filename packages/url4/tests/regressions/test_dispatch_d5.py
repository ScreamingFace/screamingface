"""Owner decision D-5 and audit E6: no ``q=`` is 400 ``missing_intent``, and the media type follows
the branch that ran.

- An endpoint or the eval path called without ``q=`` is 400 ``missing_intent`` on the node path
  (in-process and HTTP). On the direct path an endpoint is 400 too, but the eval path is refused by
  name (``direct_eval_refused``, 404) with or without ``q=``: a direct call never evaluates.
- A data route cannot be registered under the eval path.
- ``FetchResult.media_type`` comes from the branch that ran, not from a second lookup.
"""

from __future__ import annotations

import httpx
import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.io.layer import FetchRequest
from url4.peer import dispatch_direct
from url4.peer.direct import http_status
from url4.peer.server import Url4Node

pytestmark = pytest.mark.asyncio


def _node() -> Url4Node:
    node = Url4Node("d5")

    @node.endpoint("/claude")
    async def claude(request):  # type: ignore[no-untyped-def]
        return f"CLAUDE({request.context})!{request.intent}"

    @node.endpoint("/v1/chat/completions")
    async def chat(request):  # type: ignore[no-untyped-def]
        return f"CHAT({request.context})!{request.intent}"

    node.data("/api/rows", '["alpha"]', media_type="application/json")
    node.data("/plain", "hello")
    return node


def _driver(node: Url4Node) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=node.asgi())
    return httpx.AsyncClient(transport=transport, base_url="http://node")


async def test_endpoint_without_q_is_missing_intent_in_process() -> None:
    node = _node()
    with pytest.raises(ResolutionError) as exc:
        await node.fetch("/claude", relative=True)
    assert exc.value.code == ErrorCode.MISSING_INTENT == "missing_intent"
    assert exc.value.permanent is True


async def test_endpoint_without_q_is_400_over_asgi() -> None:
    async with _driver(_node()) as http:
        response = await http.get("/claude")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_intent"


@pytest.mark.parametrize("path", ["/v1", "/v1/science"])
async def test_eval_path_without_q_is_missing_intent_in_process(path: str) -> None:
    node = _node()
    with pytest.raises(ResolutionError) as exc:
        await node.fetch(path, relative=True)
    assert exc.value.code == ErrorCode.MISSING_INTENT
    assert exc.value.permanent is True


@pytest.mark.parametrize("path", ["/v1", "/v1/science"])
async def test_eval_path_without_q_is_400_over_asgi(path: str) -> None:
    async with _driver(_node()) as http:
        response = await http.get(path)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_intent"


async def test_direct_endpoint_without_q_is_missing_intent() -> None:
    with pytest.raises(ResolutionError) as exc:
        await dispatch_direct(_node(), "/claude")
    assert exc.value.code == ErrorCode.MISSING_INTENT
    assert http_status("missing_intent", permanent=True) == 400


@pytest.mark.parametrize("path", ["/v1", "/v1/science"])
async def test_direct_eval_path_without_q_is_refused_by_name(path: str) -> None:
    """Decision B: a direct call never evaluates, so the eval path without ``q=`` is refused by
    name, not answered with ``missing_intent``. The 404 is the same with or without ``q=``."""
    node = _node()
    with pytest.raises(ResolutionError) as exc:
        await dispatch_direct(node, path)
    assert exc.value.code == ErrorCode.DIRECT_EVAL_REFUSED == "direct_eval_refused"
    assert exc.value.permanent is True
    assert http_status("direct_eval_refused", permanent=True) == 404


async def test_data_route_under_eval_path_is_refused() -> None:
    node = Url4Node("d5")
    with pytest.raises(ValueError, match="eval path"):
        node.data("/v1", "x")
    with pytest.raises(ValueError, match="under the eval path"):
        node.data("/v1/x", "x")
    with pytest.raises(ValueError, match="under the eval path"):
        node.data("/v1?x=1", "x")


async def test_endpoint_under_eval_path_still_registers() -> None:
    node = _node()
    assert await node.fetch("/v1/chat/completions?q=(ctx)!go", relative=True) == "CHAT(ctx)!go"


async def test_endpoint_result_reports_no_media_type() -> None:
    result = await _node().fetch_ex(FetchRequest("/claude?q=(ctx)!go", relative=True))
    assert result.body == "CLAUDE(ctx)!go"
    assert result.media_type is None


async def test_data_route_reports_its_declared_media_type() -> None:
    result = await _node().fetch_ex(FetchRequest("/api/rows", relative=True))
    assert result.body == '["alpha"]'
    assert result.media_type == "application/json"


async def test_data_path_with_q_is_served_as_data_with_its_media_type() -> None:
    result = await _node().fetch_ex(FetchRequest("/api/rows?q=(x)!y", relative=True))
    assert result.body == '["alpha"]'
    assert result.media_type == "application/json"
