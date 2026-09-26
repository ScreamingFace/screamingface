"""`url4.peer.dispatch_direct` / `describe_routes` — the public direct-call API (spec D1).

A direct call runs ONE registered handler: an endpoint (an intent processor) or a data route.
It never evaluates an expression, so the eval path is refused — the guarantee a mount call
depends on (no grammar, no DAG, no URL-valued context).
"""

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.peer import DirectResult, RouteInfo, describe_routes, dispatch_direct
from url4.peer.server import Url4Node
from url4.wire.subrequest import encode_subrequest

pytestmark = pytest.mark.asyncio


def _node() -> tuple[Url4Node, list[object]]:
    node = Url4Node("t")
    calls: list[object] = []

    @node.endpoint("/v1/chat/completions")
    async def chat(request):  # type: ignore[no-untyped-def]
        calls.append(request)
        return f"answer to {request.intent} over {request.context}"

    node.data("/v1/benchmarks/data/foo", lambda: '{"rows": 3}', media_type="application/json")
    node.data("/plain", "hello")

    async def evaluate(*args: object, **kwargs: object) -> str:
        calls.append("EVAL")
        return "evaluated"

    node._run_text = evaluate  # type: ignore[method-assign]
    return node, calls


def _target(path: str, context: str, intent: str) -> str:
    return encode_subrequest(path, context, intent)


async def test_dispatch_direct_refuses_eval_path() -> None:
    """MNT-1 / MC-E3: the eval path and an unregistered qualified form are refused,
    permanently — while the registered mounts UNDER `/v1` are served (the tests below)."""
    node, calls = _node()
    for target in ("/v1?q=(gpt)!'hi'", "/v1/science?q=(@)!'x'"):
        with pytest.raises(ResolutionError) as exc:
            await dispatch_direct(node, target)
        assert exc.value.code == ErrorCode.DIRECT_EVAL_REFUSED == "direct_eval_refused"
        assert exc.value.permanent is True
    assert calls == []


async def test_dispatch_direct_calls_one_endpoint_handler() -> None:
    """MNT-2: one handler call with the decoded context and intent — no evaluation."""
    node, calls = _node()
    result = await dispatch_direct(node, _target("/v1/chat/completions", "ctx", "summarize"))
    assert result == DirectResult(body="answer to summarize over ctx", media_type=None)
    assert len(calls) == 1 and "EVAL" not in calls


async def test_dispatch_direct_serves_data_route_with_media_type() -> None:
    """MNT-3 / MC-D14: a data route without `q` returns the data and its media type."""
    node, _ = _node()
    assert await dispatch_direct(node, "/v1/benchmarks/data/foo") == DirectResult(
        body='{"rows": 3}', media_type="application/json"
    )
    assert await dispatch_direct(node, "/plain") == DirectResult(body="hello", media_type=None)


async def test_dispatch_direct_unknown_path_is_endpoint_not_found() -> None:
    node, _ = _node()
    with pytest.raises(ResolutionError) as exc:
        await dispatch_direct(node, "/nowhere")
    assert exc.value.code == ErrorCode.ENDPOINT_NOT_FOUND


async def test_dispatch_direct_endpoint_without_q_is_refused() -> None:
    """An intent processor needs `(context)!intent`; without `q` there is nothing to call."""
    node, calls = _node()
    with pytest.raises(ResolutionError) as exc:
        await dispatch_direct(node, "/v1/chat/completions")
    assert exc.value.code == ErrorCode.MISSING_INTENT
    assert calls == []


async def test_describe_routes_lists_endpoints_and_data_routes() -> None:
    """MNT-4: the public route listing — never the eval path."""
    node, _ = _node()
    assert describe_routes(node) == [
        RouteInfo(path="/plain", kind="data", media_type=None),
        RouteInfo(path="/v1/benchmarks/data/foo", kind="data", media_type="application/json"),
        RouteInfo(path="/v1/chat/completions", kind="endpoint", media_type=None),
    ]
