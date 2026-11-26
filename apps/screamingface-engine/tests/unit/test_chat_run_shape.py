"""FEATURE: chat-run erd §2.2 / prd CR-3 to CR-5, CR-21 — the `chat` run shape and its input ref.

A chat run carries the blob ref of its CHAT_INPUT record in its env. The run shape and the
input key must agree: a `chat` run needs the key, and no other shape may carry it. The queue
codec and the inprocess adapter render the same env for a chat run, and a chat run keeps the
run deadline, so no gateway attempt starts after it.
"""

import asyncio
import time
from collections.abc import AsyncIterator

import httpx
import pytest

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.request_scope import request_scope
from screamingface_engine.runner.main import RunnerConfigError, request_scope_from_env
from screamingface_engine.runner_queue import decode_message, encode_message
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world import gateway_transport
from url4.core.errors import ResolutionError
from url4.streaming.interfaces import ExecStep, Executor, TraceContext

REF = "blob:sha256/" + "a" * 64
RECIPE = "(model_1:0.0:/prov~a($input)!'')!'$model_1'"

# The codec's always-on keys that local mode deliberately does not write.
_CODEC_ONLY = {job_env.STREAM_GRACE_S, job_env.EXTRA_MODELS, job_env.IO_CONCURRENCY}


class _NeverExecutor(Executor):
    """Never executed — these tests assert the env the runner BUILDS, not what it then runs."""

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:  # pragma: no cover - the run is never started
        raise NotImplementedError
        yield  # pragma: no cover - unreachable; makes this an async generator


class _Gateway:
    """Records each attempt; the chat deadline test asserts that none is made."""

    def __init__(self) -> None:
        self.read_timeouts: list[float | None] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.read_timeouts.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json={"ok": True})


def _client(gateway: _Gateway, timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handler),
        base_url="http://aigateway.test",
        timeout=timeout,
    )


def test_run_shape_accepts_chat_and_requires_input_key() -> None:
    env = {job_env.RUN_SHAPE: "chat", job_env.CHAT_INPUT: REF}
    assert job_env.run_shape_from_env(env) == "chat"
    assert job_env.chat_input_from_env(env) == REF
    with pytest.raises(ValueError):
        job_env.chat_input_from_env({job_env.RUN_SHAPE: "chat"})
    with pytest.raises(ValueError):
        job_env.chat_input_from_env({job_env.RUN_SHAPE: "chat", job_env.CHAT_INPUT: ""})
    with pytest.raises(RunnerConfigError):
        request_scope_from_env({job_env.RUN_SHAPE: "chat"})
    with pytest.raises(ValueError):
        job_env.run_shape_from_env({job_env.RUN_SHAPE: "bogus"})


@pytest.mark.parametrize("shape_env", [{}, {job_env.RUN_SHAPE: "direct"}])
def test_run_shape_refuses_input_key_on_other_shapes(shape_env: dict[str, str]) -> None:
    assert job_env.chat_input_from_env(shape_env) is None
    with_key = {**shape_env, job_env.CHAT_INPUT: REF}
    with pytest.raises(ValueError):
        job_env.chat_input_from_env(with_key)
    with pytest.raises(RunnerConfigError):
        request_scope_from_env(with_key)


def test_shape_env_writes_the_keys_of_each_shape_and_refuses_a_pair_that_disagrees() -> None:
    assert job_env.shape_env("expression", None) == {}
    assert job_env.shape_env("direct", None) == {job_env.RUN_SHAPE: "direct"}
    assert job_env.shape_env("chat", REF) == {job_env.RUN_SHAPE: "chat", job_env.CHAT_INPUT: REF}
    with pytest.raises(ValueError):
        job_env.shape_env("chat", None)
    with pytest.raises(ValueError):
        job_env.shape_env("chat", "")
    with pytest.raises(ValueError):
        job_env.shape_env("expression", REF)
    with pytest.raises(ValueError):
        job_env.shape_env("direct", REF)


def test_both_adapters_refuse_a_shape_and_input_that_disagree() -> None:
    runner = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _NeverExecutor(),
    )
    with pytest.raises(ValueError):
        encode_message("topic-a", RECIPE, 60, chat_input=REF)
    with pytest.raises(ValueError):
        encode_message("topic-a", RECIPE, 60, shape="chat")
    with pytest.raises(ValueError):
        runner._env(  # noqa: SLF001
            "topic-a", RECIPE, 60, None, None, None, chat_input=REF
        )
    with pytest.raises(ValueError):
        runner._env(  # noqa: SLF001
            "topic-a", RECIPE, 60, None, None, None, shape="chat"
        )


def test_queue_and_inprocess_adapters_render_same_chat_env() -> None:
    codec = decode_message(encode_message("topic-a", RECIPE, 60, shape="chat", chat_input=REF))
    local = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _NeverExecutor(),
    )._env(  # noqa: SLF001
        "topic-a", RECIPE, 60, None, None, None, shape="chat", chat_input=REF
    )

    assert {k: v for k, v in codec.items() if k not in _CODEC_ONLY} == local
    assert codec[job_env.RUN_SHAPE] == local[job_env.RUN_SHAPE] == "chat"
    assert codec[job_env.CHAT_INPUT] == local[job_env.CHAT_INPUT] == REF
    assert float(codec[job_env.STREAM_GRACE_S]) == job_env.DIRECT_STREAM_GRACE_S

    plain = decode_message(encode_message("topic-a", RECIPE, 60))
    assert job_env.CHAT_INPUT not in plain
    assert job_env.RUN_SHAPE not in plain


def test_chat_run_scope_carries_the_run_deadline() -> None:
    before = time.monotonic()
    scope = request_scope_from_env(
        {job_env.RUN_SHAPE: "chat", job_env.CHAT_INPUT: REF, job_env.JOB_DEADLINE_S: "35"}
    )

    assert scope.origin == "run"
    assert scope.deadline is not None
    assert before + 35 <= scope.deadline <= time.monotonic() + 35


@pytest.mark.asyncio
async def test_chat_run_starts_no_gateway_attempt_after_its_deadline() -> None:
    scope = request_scope_from_env(
        {job_env.RUN_SHAPE: "chat", job_env.CHAT_INPUT: REF, job_env.JOB_DEADLINE_S: "0.001"}
    )
    await asyncio.sleep(0.01)
    gateway = _Gateway()
    async with _client(gateway, timeout=28.0) as client:
        with request_scope(scope):
            with pytest.raises(ResolutionError) as caught:
                await gateway_transport._post_completion(client, headers={}, body={})
    assert caught.value.code == "aigateway_deadline_exceeded"
    assert gateway.read_timeouts == []
