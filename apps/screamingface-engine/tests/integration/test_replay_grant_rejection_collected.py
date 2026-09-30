"""E14 (RP-14f) — the full RP-E6 path: a collected grant rejection still fails the run.

FEATURE: reproducible submissions (OME-1307). The real connector gets `403 replay_grant_invalid`,
a benchmark endpoint catches the `ResolutionError` as a failed case and returns an answer, and the
run must STILL fail with the typed error and never reach `Completed`.

INVARIANT (RP-E6, CV-E4): the connector itself reports the rejection to the run's sink
(`report_grant_rejection` in `_raise_for_status`). This test uses no direct sink call, so it pins
that report: without it the run would complete with a failed case instead of failing.
"""

from __future__ import annotations

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.peer.server import Request, Url4Node
from url4.streaming.interfaces import Completed

MODEL = "anthropic/claude-haiku-4-5"
GRANT = "eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0.eyJ2aWQiOiJ2In0.c2ln"


def _handle(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        403,
        json={"detail": {"code": "replay_grant_invalid", "reason": "subject"}},
    )


@pytest.mark.asyncio
async def test_a_collected_rejection_still_fails_the_run_with_the_typed_error() -> None:
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    collected: list[str] = []
    frames: list[object] = []

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(cfg, client=client)
        node = Url4Node("bench", default_processor="/m")

        async def handler(request: Request) -> str:
            # A benchmark case: the model call fails, the case is recorded as failed, and the
            # endpoint still answers, so the run would otherwise complete.
            try:
                await url4_run(f"/{MODEL}('ctx')!'go'", world.node)
            except ResolutionError as exc:
                collected.append(exc.code)
            return "ok"

        node.endpoint("/m")(handler)
        executor = Url4Executor(
            node,
            request_scope_factory=lambda: RequestScope(origin="run", replay_grant=GRANT),
        )

        with pytest.raises(ResolutionError) as raised:
            async for frame in executor.execute("/m('x')!'go'"):
                frames.append(frame)

    assert collected == ["replay_grant_invalid"]
    assert raised.value.code == "replay_grant_invalid"
    assert raised.value.permanent is True
    assert "reason=subject" in str(raised.value)
    assert not any(isinstance(frame, Completed) for frame in frames)
