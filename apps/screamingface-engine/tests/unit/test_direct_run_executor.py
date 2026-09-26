"""The run child's `direct` shape (uniform executor PRD 04): a mount call runs ONE handler via
`url4.peer.dispatch_direct`, never a DAG — and its model call still yields span + cost frames.
"""

import pytest

from screamingface_engine.runner.executor import Url4Executor
from url4.core.errors import ResolutionError
from url4.observe import current_response_sink, current_usage_sink
from url4.peer.server import Url4Node
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.protocol import CostUsageData, SpanData
from url4.wire.subrequest import encode_subrequest

pytestmark = pytest.mark.asyncio


def _node() -> tuple[Url4Node, list[str]]:
    node = Url4Node("world")
    calls: list[str] = []

    @node.endpoint("/v1/chat/completions")
    async def chat(request):  # type: ignore[no-untyped-def]
        calls.append(request.intent)
        usage, response = current_usage_sink(), current_response_sink()
        assert usage is not None and response is not None
        usage(provider="openrouter", model="m", input_tokens=4, output_tokens=6)
        response(finish_reason="stop", refusal=None)
        return '{"answer": 42}'

    node.data("/v1/benchmarks/data/foo", '{"rows": 1}', media_type="application/json")

    async def evaluate(*args: object, **kwargs: object) -> str:
        calls.append("EVAL")
        return "evaluated"

    node._run_text = evaluate  # type: ignore[method-assign]
    return node, calls


async def _steps(executor: Url4Executor, target: str) -> list[object]:
    return [step async for step in executor.execute(target)]


async def test_direct_shape_runs_dispatch_direct_not_dag() -> None:
    """MNT-6 / MC-H2: one handler call; the DAG evaluator is never reached."""
    node, calls = _node()
    executor = Url4Executor(node, run_shape="direct")
    steps = await _steps(executor, encode_subrequest("/v1/chat/completions", "hi", "answer"))
    completed = steps[-1]
    assert isinstance(completed, Completed)
    assert completed.result.body == '{"answer": 42}'
    assert calls == ["answer"]


async def test_direct_run_yields_span_and_cost_for_the_model_call() -> None:
    """MNT-8 (unit half) / MC-H3: the handler's usage becomes one span and one self cost
    frame, and the subtree cost carries it."""
    node, _ = _node()
    steps = await _steps(
        Url4Executor(node, run_shape="direct"),
        encode_subrequest("/v1/chat/completions", "hi", "answer"),
    )
    payloads = [s.payload for s in steps if isinstance(s, Traced)]
    spans = [p for p in payloads if isinstance(p, SpanData)]
    costs = [p for p in payloads if isinstance(p, CostUsageData)]
    assert len(spans) == 1 and spans[0].name == "/v1/chat/completions"
    assert spans[0].input_tokens == 4 and spans[0].output_tokens == 6
    assert [c.scope for c in costs] == ["self"]
    completed = steps[-1]
    assert isinstance(completed, Completed)
    assert completed.subtree_cost.usage.input_tokens == 4


async def test_a_direct_data_route_keeps_its_media_type() -> None:
    """MC-D14: the handler's declared media type reaches the result frame."""
    node, _ = _node()
    steps = await _steps(Url4Executor(node, run_shape="direct"), "/v1/benchmarks/data/foo")
    completed = steps[-1]
    assert isinstance(completed, Completed)
    assert completed.result.body == '{"rows": 1}'
    assert completed.result.media_type == "application/json"


async def test_tampered_eval_target_fails_direct_eval_refused() -> None:
    """MNT-7 / MC-D1: a queue message whose direct target is the eval path fails with
    `direct_eval_refused`, and nothing is evaluated."""
    node, calls = _node()
    with pytest.raises(ResolutionError) as exc:
        await _steps(Url4Executor(node, run_shape="direct"), "/v1?q=(gpt)!'hi'")
    assert exc.value.code == "direct_eval_refused"
    assert calls == []


async def test_expression_shape_is_unchanged() -> None:
    """The default shape still evaluates the expression."""
    node, calls = _node()
    steps = await _steps(Url4Executor(node), "'hello'")
    assert isinstance(steps[-1], Completed)
    assert "EVAL" not in calls  # a literal needs no node evaluation either
