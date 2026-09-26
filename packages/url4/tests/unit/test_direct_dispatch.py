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


class _Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def on_event(self, event: object) -> None:
        self.events.append(event)


async def test_an_observed_direct_call_reports_one_node_with_its_usage() -> None:
    """PRD 04 MC-H3 / MNT-8: a direct call emits what a one-node run emits — RunStarted, one
    NodeStarted / NodeFinished pair, and the handler's usage and response on THAT span — so a
    host maps it to the same span and cost frames, with no DAG."""
    from url4.observe import (
        ModelResponse,
        NodeFinished,
        NodeStarted,
        RunFinished,
        RunStarted,
        Usage,
        current_response_sink,
        current_usage_sink,
    )

    node = Url4Node("t")

    @node.endpoint("/v1/chat/completions")
    async def chat(request):  # type: ignore[no-untyped-def]
        sink, response = current_usage_sink(), current_response_sink()
        assert sink is not None and response is not None
        sink(provider="p", model="m", input_tokens=3, output_tokens=5)
        response(finish_reason="stop", refusal=None)
        return "ok"

    recorder = _Recorder()
    trace_id, root = "a" * 32, "b" * 16
    await dispatch_direct(
        node,
        _target("/v1/chat/completions", "ctx", "i"),
        observer=recorder,
        trace_id=trace_id,
        root_span_id=root,
    )
    kinds = [type(e) for e in recorder.events]
    assert kinds == [RunStarted, NodeStarted, Usage, ModelResponse, NodeFinished, RunFinished]
    run, started, usage, response, finished, done = recorder.events
    assert (run.trace_id, run.root_span_id) == (trace_id, root)  # type: ignore[attr-defined]
    assert started.parent_span_id == root and started.detail == "/v1/chat/completions"  # type: ignore[attr-defined]
    span = started.span_id  # type: ignore[attr-defined]
    assert usage.span_id == response.span_id == finished.span_id == span  # type: ignore[attr-defined]
    assert (usage.input_tokens, usage.output_tokens) == (3, 5)  # type: ignore[attr-defined]
    assert finished.status == "ok" and done.status == "ok"  # type: ignore[attr-defined]


async def test_an_observed_direct_call_reports_a_log_line_on_its_span() -> None:
    """C10: a handler's `current_log_sink()` record is not dropped for a direct call —
    it reaches the observer as a `Log` on the node's span, between NodeStarted and
    NodeFinished, the same as a DAG run keeps it."""
    from url4.observe import Log, NodeFinished, NodeStarted, current_log_sink

    node = Url4Node("t")

    @node.endpoint("/v1/chat/completions")
    async def chat(request):  # type: ignore[no-untyped-def]
        sink = current_log_sink()
        assert sink is not None
        sink("hello from handler", {"k": "v"}, severity="warn")
        return "ok"

    recorder = _Recorder()
    await dispatch_direct(
        node, _target("/v1/chat/completions", "ctx", "i"), observer=recorder
    )
    kinds = [type(e) for e in recorder.events]
    assert kinds.count(Log) == 1
    started_idx = kinds.index(NodeStarted)
    finished_idx = kinds.index(NodeFinished)
    log_idx = kinds.index(Log)
    assert started_idx < log_idx < finished_idx
    log_event = recorder.events[log_idx]
    assert log_event.span_id == recorder.events[started_idx].span_id  # type: ignore[attr-defined]
    assert log_event.severity == "WARN"  # type: ignore[attr-defined]
    assert log_event.body == "hello from handler"  # type: ignore[attr-defined]
    assert dict(log_event.attributes) == {"k": "v"}  # type: ignore[attr-defined]


async def test_an_observed_failed_direct_call_finishes_its_node_with_the_code() -> None:
    node, _ = _node()
    recorder = _Recorder()
    with pytest.raises(ResolutionError):
        await dispatch_direct(node, "/v1?q=x", observer=recorder)
    from url4.observe import NodeFinished, RunFinished

    finished = [e for e in recorder.events if isinstance(e, NodeFinished)]
    assert [(f.status, f.code) for f in finished] == [("error", "direct_eval_refused")]
    assert [e.status for e in recorder.events if isinstance(e, RunFinished)] == ["error"]


async def test_http_status_of_a_failed_direct_call() -> None:
    """A queued direct call answers its caller as the node would have."""
    from url4.peer import http_status

    assert http_status("malformed_source", permanent=True) == 400
    assert http_status("missing_intent", permanent=True) == 400
    assert http_status("endpoint_not_found", permanent=True) == 404
    assert http_status("direct_eval_refused", permanent=True) == 404
    assert http_status("identity_access_denied", permanent=True) == 403
    assert http_status("some_upstream_blip", permanent=False) == 502
    assert http_status(None, permanent=True) == 500
