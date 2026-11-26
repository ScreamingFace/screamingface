"""The final step on the shared gateway round trip (tool-calls PRD TC-S16, TC-S24, TC-S25).

FEATURE: tool-calls. The final step keeps the cache policy, the cache read-back, the Candidate
retry and the refusal path of every other step, and a run with two final results fails: the
Engine never picks one.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from _chat_final_world import (
    Reply,
    ToolGateway,
    call_final,
    chat_run,
    final_recipe,
    final_route,
    final_turn,
    tool_call,
    tools_world,
)

from screamingface_engine.benchmarks.contract import decode_candidate_invocation_record
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.candidate_scope import candidate_invocation_scope
from screamingface_engine.model_outcomes import model_outcome_from_error
from screamingface_engine.operation_calls import OperationCall, capture_operation_calls
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world import candidate_call_retry, gateway_transport
from screamingface_engine.world.cache import policy_to_body_field
from screamingface_engine.world.chat_final import (
    FINAL_STEP_AMBIGUOUS,
    FinalCall,
    FinalCalls,
    final_turn_scope,
)
from url4 import RelExpr, expr, render, src, text
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node
from url4.streaming.protocol import CachePolicy

pytestmark = pytest.mark.asyncio

MODEL = "prov/a"


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each retry wait is zero, as in test_candidate_call_retry."""

    async def no_wait(_attempt: int, _delay: float) -> None:
        return None

    monkeypatch.setattr(gateway_transport, "_wait_to_retry", no_wait)
    monkeypatch.setattr(candidate_call_retry, "_jitter", lambda _low, _high: 0.0)
    yield


def _call(binding: str) -> FinalCall:
    return FinalCall(binding, (), "stop", None)


def _plain_recipe(model: str) -> str:
    """One source on the plain model route of `model`, with `$input` as context."""
    return render(
        expr(
            src(
                RelExpr(path="/" + model, context="$input", intent=text("")),
                name="model_1",
                weight=0.0,
            ),
            intent=text("$model_1"),
        )
    )


async def _plain_call(node: Url4Node, input_text: str) -> OperationCall:
    with request_scope(RequestScope(origin="run")), capture_operation_calls() as operations:
        await node.evaluate(_plain_recipe(MODEL), env={"input": input_text})
    assert len(operations) == 1
    return operations[0]


async def test_two_final_results_fail_with_final_step_ambiguous() -> None:
    calls = FinalCalls()
    assert calls.result() is None
    first = _call("model_1")
    calls.add(first)
    assert calls.result() is first
    calls.add(_call("model_2"))
    with pytest.raises(ResolutionError) as ambiguous:
        calls.result()
    assert ambiguous.value.code == FINAL_STEP_AMBIGUOUS == "final_step_ambiguous"
    assert ambiguous.value.permanent is True
    assert "model_1" not in str(ambiguous.value) and "model_2" not in str(ambiguous.value)

    gateway = ToolGateway({MODEL: Reply(content="ok", tool_calls=[tool_call()])})
    turn = final_turn()
    recipe = render(
        expr(
            src(
                RelExpr(
                    path=final_route(MODEL),
                    context="$input",
                    intent=text(""),
                    params=(("binding", "model_1"),),
                ),
                name="model_1",
                weight=0.0,
            ),
            src(
                RelExpr(
                    path=final_route(MODEL),
                    context="$model_1",
                    intent=text(""),
                    params=(("binding", "model_2"),),
                ),
                name="model_2",
                weight=0.0,
            ),
            intent=text("$model_2"),
        )
    )
    async with tools_world(gateway) as node:
        with request_scope(RequestScope(origin="run")), chat_run(), final_turn_scope(turn):
            await node.evaluate(recipe, env={"input": turn.input_text})

    assert len(gateway.seen) == 2
    assert len(turn.calls) == 2
    with pytest.raises(ResolutionError) as twice:
        turn.calls.result()
    assert twice.value.code == FINAL_STEP_AMBIGUOUS


async def test_final_step_honours_no_store_and_reports_cache_hit() -> None:
    policy = CachePolicy(participate=False)
    gateway = ToolGateway({MODEL: Reply(content="fresh")})
    async with tools_world(gateway) as node:
        await call_final(
            node, MODEL, turn=final_turn(), scope=RequestScope(origin="run", cache=policy)
        )
    assert policy_to_body_field(policy) == {"cache": {"use-cache": False}}
    assert gateway.seen[0]["cache"] == policy_to_body_field(policy)["cache"]

    hit = ToolGateway({MODEL: Reply(content="stored", cache="hit")})
    turn = final_turn()
    async with tools_world(hit) as node:
        await call_final(node, MODEL, turn=turn)
        plain = await _plain_call(node, turn.input_text)
    final = turn.calls.result()
    assert final is not None and final.accounting is not None
    assert plain.accounting is not None
    assert final.accounting.cache == plain.accounting.cache
    assert final.accounting.cache.hits == 1
    assert final.accounting == plain.accounting


async def test_final_step_retries_429_like_other_candidate_calls() -> None:
    busy = Reply(status=429, error_code="rate_limited")
    gateway = ToolGateway({MODEL: [busy, Reply(content="ok")]})
    async with tools_world(gateway) as node:
        with candidate_invocation_scope():
            answer = await call_final(node, MODEL, turn=final_turn())
    assert answer == "ok"
    assert len(gateway.seen) == 2
    assert gateway.seen[0] == gateway.seen[1]

    final_gateway = ToolGateway({MODEL: [busy, Reply(content="ok")]})
    async with tools_world(final_gateway) as node:
        with pytest.raises(ResolutionError) as final_error:
            await call_final(node, MODEL, turn=final_turn())
    plain_gateway = ToolGateway({MODEL: [busy, Reply(content="ok")]})
    async with tools_world(plain_gateway) as node:
        with pytest.raises(ResolutionError) as plain_error:
            await _plain_call(node, final_turn().input_text)
    assert len(final_gateway.seen) == len(plain_gateway.seen) == 1
    assert final_error.value.code == plain_error.value.code
    assert final_error.value.permanent == plain_error.value.permanent


async def test_refused_final_step_gives_refused_result() -> None:
    refusal = Reply(content=None, finish_reason="content_filter", refusal="no")
    gateway = ToolGateway({MODEL: refusal})
    async with tools_world(gateway) as node:
        with pytest.raises(ResolutionError) as refused:
            await call_final(node, MODEL, turn=final_turn())
        outcome = model_outcome_from_error(refused.value)
        assert refused.value.code == "provider_refusal"
        assert outcome is not None and outcome.finish_reason == "content_filter"

        turn = final_turn()
        with (
            request_scope(RequestScope(origin="run")),
            candidate_invocation_scope(),
            chat_run(),
            final_turn_scope(turn),
        ):
            envelope = await evaluate_candidate_recipe(node, final_recipe(MODEL), turn.input_text)
    invocation = decode_candidate_invocation_record(envelope)
    assert invocation.status == "refused"
    assert invocation.refusal == "no"
