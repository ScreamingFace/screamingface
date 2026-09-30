"""E14 (RP-14) — a replay grant the gateway rejects fails the run with a typed error.

FEATURE: reproducible submissions (OME-1307). A replay must never become a live run in silence
(RP-E6, CV-E4). When aigateway answers `403 {"detail": {"code": "replay_grant_invalid", ...}}`:

    connector ──► ResolutionError(code="replay_grant_invalid", permanent=True)
              └─► the run's sink records the reason ──► the run fails, even when a benchmark
                  collected the failed call as a failed case

INVARIANT: the error text carries the closed reason only. It never carries the gateway's message
or the grant, and the engine never retries the call without the grant.

LIMIT (D4): a grant lives 12 h and can expire mid-run. That is a documented, accepted limit; the
run then fails with reason `expired` (RP-14e). There is no refresh.
"""

from __future__ import annotations

import httpx
import pytest

from screamingface_engine.replay_outcomes import report_grant_rejection
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.peer.server import Request, Url4Node
from url4.streaming.interfaces import Completed

MODEL = "anthropic/claude-haiku-4-5"
GRANT = "eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0.eyJ2aWQiOiJ2In0.c2ln"
GATEWAY_MESSAGE = "gw-secret"
_REPLAY_HEADER = "x-aigw-cache-replay"


def _rejection(reason: str) -> httpx.Response:
    return httpx.Response(
        403,
        json={
            "detail": {
                "code": "replay_grant_invalid",
                "reason": reason,
                "message": GATEWAY_MESSAGE,
            }
        },
    )


def _answer() -> httpx.Response:
    return httpx.Response(
        200,
        headers={"X-AIGW-Cache-Version": "hit", "X-AIGW-Cache": "hit"},
        json={
            "choices": [{"message": {"role": "assistant", "content": "an answer"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


class _Gateway:
    """A chat-completions endpoint that answers call N with the Nth prepared response."""

    def __init__(self, answers: list[httpx.Response]) -> None:
        self._answers = answers
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        index = len(self.requests)
        self.requests.append(request)
        return self._answers[min(index, len(self._answers) - 1)]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )


def _scope() -> RequestScope:
    return RequestScope(origin="run", replay_grant=GRANT)


async def _run_direct(gateway: _Gateway) -> None:
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gateway.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        with request_scope(_scope()):
            await url4_run(f"/{MODEL}('ctx')!'go'", world.node)


async def _execute(gateway: _Gateway, expression: str) -> list[object]:
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gateway.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(world.node, request_scope_factory=_scope)
        return [frame async for frame in executor.execute(expression)]


# --- RP-14a/b: the connector's typed error ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_rejected_grant_raises_a_typed_permanent_error() -> None:
    gateway = _Gateway([_rejection("expired")])

    with pytest.raises(ResolutionError) as raised:
        await _run_direct(gateway)

    assert raised.value.code == "replay_grant_invalid"
    assert raised.value.permanent is True
    assert "reason=expired" in str(raised.value)
    assert GATEWAY_MESSAGE not in str(raised.value)
    assert GRANT not in str(raised.value)


@pytest.mark.asyncio
async def test_an_unknown_reason_reads_as_unknown() -> None:
    gateway = _Gateway([_rejection("rotated")])

    with pytest.raises(ResolutionError) as raised:
        await _run_direct(gateway)

    assert "reason=unknown" in str(raised.value)
    assert "rotated" not in str(raised.value)


@pytest.mark.asyncio
async def test_a_rejection_without_a_reason_reads_as_unknown() -> None:
    gateway = _Gateway(
        [httpx.Response(403, json={"detail": {"code": "replay_grant_invalid", "message": "m"}})]
    )

    with pytest.raises(ResolutionError) as raised:
        await _run_direct(gateway)

    assert raised.value.code == "replay_grant_invalid"
    assert "reason=unknown" in str(raised.value)


@pytest.mark.asyncio
async def test_a_403_that_is_not_a_grant_rejection_keeps_its_own_code() -> None:
    gateway = _Gateway(
        [httpx.Response(403, json={"detail": {"code": "forbidden", "message": "no"}})]
    )

    with pytest.raises(ResolutionError) as raised:
        await _run_direct(gateway)

    assert raised.value.code == "forbidden"


# --- RP-14c: the run fails even when a benchmark collected the failed call --------------------


@pytest.mark.asyncio
async def test_grant_rejected_mid_run_fails_run_with_typed_error() -> None:
    def handler(request: Request) -> str:
        # A benchmark that COLLECTED the failure as a failed case: it reports the rejection and
        # still returns an answer, so the run would otherwise complete.
        report_grant_rejection("subject")
        return "ok"

    node = Url4Node("t", default_processor="/m")
    node.endpoint("/m")(handler)
    frames: list[object] = []

    with pytest.raises(ResolutionError) as raised:
        async for frame in Url4Executor(node).execute("/m('x')!'go'"):
            frames.append(frame)

    assert raised.value.code == "replay_grant_invalid"
    assert raised.value.permanent is True
    assert "reason=subject" in str(raised.value)
    assert not any(isinstance(frame, Completed) for frame in frames)


# --- RP-14d/e: no live fallback, and the documented mid-run expiry ----------------------------


@pytest.mark.asyncio
async def test_a_rejection_never_falls_through_to_a_live_call() -> None:
    gateway = _Gateway([_rejection("signature")])

    with pytest.raises(ResolutionError):
        await _execute(gateway, f"/{MODEL}('ctx')!'go'")

    assert gateway.requests
    assert all(_REPLAY_HEADER in request.headers for request in gateway.requests)


@pytest.mark.asyncio
async def test_a_grant_that_expires_mid_run_fails_the_run_with_reason_expired() -> None:
    gateway = _Gateway([_answer(), _rejection("expired")])
    frames: list[object] = []
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)

    with pytest.raises(ResolutionError) as raised:
        async with gateway.client() as client:
            world = await build_aigateway_world(cfg, client=client)
            executor = Url4Executor(world.node, request_scope_factory=_scope)
            async for frame in executor.execute(f"/{MODEL}(/{MODEL}('a')!'x')!'y'"):
                frames.append(frame)

    assert raised.value.code == "replay_grant_invalid"
    assert raised.value.permanent is True
    assert "reason=expired" in str(raised.value)
    assert GATEWAY_MESSAGE not in str(raised.value)
    assert GRANT not in str(raised.value)
    assert not any(isinstance(frame, Completed) for frame in frames)
    assert len(gateway.requests) == 2
    assert all(request.headers[_REPLAY_HEADER] == GRANT for request in gateway.requests)
