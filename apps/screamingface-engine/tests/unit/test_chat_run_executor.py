"""The executor branch of the `chat` run shape (chat-run PRD CR-S1, CR-S3, CR-S5, CR-S10,
CR-S12, CR-S14; contracts C7, C9).

FEATURE: chat-run. A `chat` run dispatches the internal turn route `/ensemble/chat/v1/turn` as
ONE observed node. The run states the CHAT_RESULT media type, its span carries the usage of every
model call of the recipe, and a failed or stopped run publishes no result.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from _chat_world import FAIL, Gateway, chat_store, chat_world, ingest_chat_input

from screamingface_engine import job_env
from screamingface_engine.artifacts.blobs import BLOB_REF_PREFIX
from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.artifacts.ports import LocalFile
from screamingface_engine.chat.recipe import one_model_recipe
from screamingface_engine.chat.result import CHAT_RESULT_MEDIA_TYPE, ChatResult, decode_chat_result
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.runner.main import build_executor
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from screamingface_engine.world.chat_turn import CHAT_TURN_ROUTE
from screamingface_engine.world.config import WorldConfig
from url4 import RelExpr, expr, render, src, text
from url4.core.errors import ResolutionError
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.protocol import CostUsageData, SpanData

MODEL = "prov/a"
SYNTH = "prov/b"
RECIPE = one_model_recipe(MODEL)
MESSAGES = [{"role": "user", "content": "Capital of France?"}]


class _PricedGateway(Gateway):
    """The stub gateway with a run-level price: 0.001 credits per answered call.

    WHY: the shared stub body states the attempt cost but an empty `known_direct_cost_subtotals`,
    so `usd_from_aigw` leaves each call unpriced. Only the price is added here.
    """

    async def handle(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle(request)
        if response.status_code != 200:
            return response
        body = response.json()
        body["_aigw"]["request_economics"]["known_direct_cost_subtotals"] = [
            {"unit": "openrouter_credits", "amount": "0.001"}
        ]
        return httpx.Response(200, headers={"X-AIGW-Cache": "miss"}, json=body)


async def _steps(executor: Url4Executor, recipe: str) -> list[object]:
    return [step async for step in executor.execute(recipe)]


def _completed(steps: list[object]) -> Completed:
    completed = steps[-1]
    assert isinstance(completed, Completed)
    return completed


def _inline_result(completed: Completed) -> ChatResult:
    body = completed.result.body
    assert body is not None
    return decode_chat_result(body.encode("utf-8"))


def _member(name: str, answer: str) -> Any:
    return src(
        RelExpr(path="/" + MODEL, context="$input", intent=text(answer)), name=name, weight=0.0
    )


def _three_call_recipe() -> str:
    """model_1 and model_2 on one route with one params set, then synthesis_1 over both."""
    synthesis = src(
        RelExpr(path="/" + SYNTH, context="$model_1 $model_2", intent=text("Merge")),
        name="synthesis_1",
        weight=0.0,
    )
    return render(
        expr(
            _member("model_1", "Answer A"),
            _member("model_2", "Answer B"),
            synthesis,
            intent=text("$synthesis_1"),
        )
    )


@pytest.mark.asyncio
async def test_chat_handler_runs_as_observed_node_and_run_summary_has_cost() -> None:
    """CR-18: the turn route is ONE span with one self cost frame; the result is typed."""
    gateway = _PricedGateway({MODEL: "Paris"})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)

    async with chat_world(gateway) as node:
        executor = Url4Executor(node, run_shape="chat", chat_input=ref, chat_input_reader=reader)
        steps = await _steps(executor, RECIPE)

    payloads = [s.payload for s in steps if isinstance(s, Traced)]
    spans = [p for p in payloads if isinstance(p, SpanData)]
    costs = [p for p in payloads if isinstance(p, CostUsageData)]
    assert [s.name for s in spans] == [CHAT_TURN_ROUTE]
    assert [c.scope for c in costs] == ["self"]
    completed = _completed(steps)
    assert completed.result.media_type == CHAT_RESULT_MEDIA_TYPE
    assert _inline_result(completed).status == "answered"
    summary = executor.last_summary()
    assert summary is not None
    assert summary.cost_usd == Decimal("0.001")


@pytest.mark.asyncio
async def test_chat_run_subtree_frame_sums_tokens_and_cost_of_every_model_call() -> None:
    """CR-9: the span sums every model call, members whose accounting attribution drops too."""
    gateway = _PricedGateway({MODEL: "member", SYNTH: "merged"})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)

    async with chat_world(gateway) as node:
        executor = Url4Executor(node, run_shape="chat", chat_input=ref, chat_input_reader=reader)
        steps = await _steps(executor, _three_call_recipe())

    assert len(gateway.seen) == 3
    completed = _completed(steps)
    assert completed.subtree_cost.usage.input_tokens == 30
    assert completed.subtree_cost.usage.output_tokens == 12
    assert completed.subtree_cost.cost.total_usd == Decimal("0.003")
    result = _inline_result(completed)
    assert result.content == "merged"
    # The attributed final step holds only its own call; the two members reach the sum via the span.
    assert result.final_step is not None
    assert result.final_step.binding == "synthesis_1"
    assert result.final_step.usage == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
    }


@pytest.mark.asyncio
async def test_failed_recipe_publishes_error_frame_and_no_result() -> None:
    """CR-11: a failed model call ends the run with the transport's code and no result."""
    gateway = Gateway({MODEL: FAIL})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)
    collected: list[object] = []

    async with chat_world(gateway) as node:
        executor = Url4Executor(node, run_shape="chat", chat_input=ref, chat_input_reader=reader)
        with pytest.raises(ResolutionError) as exc:
            async for step in executor.execute(RECIPE):
                collected.append(step)

    assert not any(isinstance(step, Completed) for step in collected)
    assert exc.value.code == "aigateway_http_400"
    assert exc.value.permanent
    summary = executor.last_summary()
    assert summary is not None and summary.outcome == "failed"


@pytest.mark.asyncio
async def test_stopped_chat_run_publishes_no_result() -> None:
    """CR-14: a cancelled chat run yields no Completed frame and records `stopped`."""
    gateway = Gateway({MODEL: "late"}, delays={MODEL: 30})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)
    collected: list[object] = []

    async with chat_world(gateway) as node:
        executor = Url4Executor(node, run_shape="chat", chat_input=ref, chat_input_reader=reader)

        async def _collect() -> None:
            async for step in executor.execute(RECIPE):
                collected.append(step)

        task = asyncio.ensure_future(_collect())
        for _ in range(200):
            if gateway.seen:
                break
            await asyncio.sleep(0.01)
        assert gateway.seen
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert not any(isinstance(step, Completed) for step in collected)
    summary = executor.last_summary()
    assert summary is not None and summary.outcome == "stopped"


@pytest.mark.asyncio
async def test_result_over_inline_cap_is_read_from_artifact_store(tmp_path: Path) -> None:
    """CR-16: a CHAT_RESULT over the inline cap spills to the store and keeps its media type."""
    answer = "Paris " * 40
    gateway = Gateway({MODEL: answer})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)
    artifacts = FilesystemArtifactStore(tmp_path)

    async with chat_world(gateway) as node:
        executor = Url4Executor(
            node,
            run_shape="chat",
            chat_input=ref,
            chat_input_reader=reader,
            result_cap=64,
            artifact_store=artifacts,
        )
        completed = _completed(await _steps(executor, RECIPE))

    assert completed.result.body is None
    assert completed.result.media_type == CHAT_RESULT_MEDIA_TYPE
    artifact = completed.result.artifact
    assert artifact is not None
    content = artifacts.content(artifact.id)
    assert isinstance(content, LocalFile)
    result = decode_chat_result(content.path.read_bytes())
    assert result.status == "answered"
    assert result.content == answer


def _echo_last_user(sent: dict[str, Any]) -> str:
    users = [m for m in sent["messages"] if m["role"] == "user"]
    return str(users[-1]["content"])


@pytest.mark.asyncio
async def test_two_parallel_chat_runs_share_no_state() -> None:
    """CR-17: two chat runs on one node, each over its own input scope, see only their own input."""
    gateway = Gateway({MODEL: _echo_last_user})
    store, _ = chat_store()
    ref_a, reader_a = ingest_chat_input(store, [{"role": "user", "content": "alpha"}], run="a" * 64)
    ref_b, reader_b = ingest_chat_input(store, [{"role": "user", "content": "beta"}], run="b" * 64)

    async with chat_world(gateway) as node:
        run_a = Url4Executor(node, run_shape="chat", chat_input=ref_a, chat_input_reader=reader_a)
        run_b = Url4Executor(node, run_shape="chat", chat_input=ref_b, chat_input_reader=reader_b)
        steps_a, steps_b = await asyncio.gather(_steps(run_a, RECIPE), _steps(run_b, RECIPE))

    content_a = _inline_result(_completed(steps_a)).content
    content_b = _inline_result(_completed(steps_b)).content
    assert "alpha" in content_a and "beta" not in content_a
    assert "beta" in content_b and "alpha" not in content_b


def _inner(executor: OperationCapturingExecutor) -> Url4Executor:
    inner = executor._inner  # noqa: SLF001 - the wiring under test
    assert isinstance(inner, Url4Executor)
    return inner


def test_build_executor_wires_the_chat_shape(tmp_path: Path) -> None:
    """C9: the run env's shape and key reach the executor; the store is not touched at build."""
    blobs = tmp_path / "blobs"
    ref = BLOB_REF_PREFIX + "ab" * 32
    env = {
        job_env.TOPIC: "t" * 64,
        job_env.EXPRESSION: RECIPE,
        job_env.RUN_SHAPE: "chat",
        job_env.CHAT_INPUT: ref,
        job_env.BLOB_STORE: "filesystem",
        job_env.BLOBS_DIR: str(blobs),
    }

    inner = _inner(build_executor(env, WorldConfig()))

    assert inner._run_shape == "chat"  # noqa: SLF001
    assert inner._chat_input == ref  # noqa: SLF001
    assert inner._chat_input_reader is not None  # noqa: SLF001
    assert not blobs.exists()

    plain = _inner(
        build_executor(
            {job_env.TOPIC: "t" * 64, job_env.EXPRESSION: RECIPE, job_env.CHAT_INPUT: ref},
            WorldConfig(),
        )
    )
    assert plain._run_shape == "expression"  # noqa: SLF001
    assert plain._chat_input is None  # noqa: SLF001
    assert plain._chat_input_reader is None  # noqa: SLF001


def test_build_executor_reads_the_chat_input_through_the_job_env_rule(tmp_path: Path) -> None:
    """C9: one rule owns the key; a pair that disagrees gives no input, and the run then fails."""
    env = {
        job_env.TOPIC: "t" * 64,
        job_env.EXPRESSION: RECIPE,
        job_env.RUN_SHAPE: "chat",
        job_env.CHAT_INPUT: "",
        job_env.BLOB_STORE: "filesystem",
        job_env.BLOBS_DIR: str(tmp_path / "blobs"),
    }

    inner = _inner(build_executor(env, WorldConfig()))

    assert inner._run_shape == "chat"  # noqa: SLF001
    assert inner._chat_input is None  # noqa: SLF001
