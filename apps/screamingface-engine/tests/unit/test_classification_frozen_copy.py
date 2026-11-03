"""A capture or replay run that calls `/classify`, through the real executor (OME-1795).

FEATURE: hosted BYOM, Unit 3, owner decision 6. A capture run opens its frozen copy before the
expression and seals it after, so a refusal inside `/classify` cannot mean zero Gateway requests.
The boundary is no classification request and no upstream inference: the existing open and seal
stay, and the handler refuses before `POST /v1/classifications`. A replay run opens no copy, so it
makes no Gateway request at all.

WHY the real `Url4Executor` on a `build_world` world: the executor is what opens and seals the
copy, and `build_world` is where `/classify` is registered in production. The simulated binding
in `frozen_copy_support.run_call` plays the executor's open step instead of running it, so it
cannot prove this boundary.
"""

from __future__ import annotations

import pytest
from frozen_copy_support import OPEN, SEAL, Gateway, capture_scope, replay_scope

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world.classification import (
    CLASSIFICATION_UNSUPPORTED,
    CLASSIFICATIONS_PATH,
)
from screamingface_engine.world.config import AigatewaySection, ModelSpec, WorldConfig
from screamingface_engine.world.factory import build_world
from url4.core.errors import ResolutionError
from url4.streaming.interfaces import Traced
from url4.streaming.protocol import CostUsageData

pytestmark = [pytest.mark.asyncio, pytest.mark.no_default_scope]

_MODEL = "anthropic/claude-haiku-4-5"
_EXPRESSION = "/classify(ctx)!classify"


def _config() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=_MODEL,
            models=(ModelSpec(id=_MODEL, web_search=False),),
        )
    )


async def _run(scope: RequestScope) -> tuple[Gateway, ResolutionError | None, list[object]]:
    gateway = Gateway()
    failure: ResolutionError | None = None
    payloads: list[object] = []
    async with gateway.client() as client:
        world, aclose = await build_world(env={}, config=_config(), client=client)
        try:
            executor = Url4Executor(world)
            with request_scope(scope):
                try:
                    async for step in executor.execute(_EXPRESSION):
                        if isinstance(step, Traced):
                            payloads.append(step.payload)
                except ResolutionError as exc:
                    failure = exc
        finally:
            if aclose is not None:
                await aclose()
    return gateway, failure, payloads


async def test_a_capture_run_makes_only_the_frozen_copy_requests() -> None:
    gateway, failure, payloads = await _run(capture_scope())

    assert gateway.paths() == [OPEN, SEAL]
    assert CLASSIFICATIONS_PATH not in gateway.paths()
    assert failure is not None and failure.code == CLASSIFICATION_UNSUPPORTED
    assert not [p for p in payloads if isinstance(p, CostUsageData)]


async def test_a_replay_run_makes_no_gateway_request() -> None:
    gateway, failure, payloads = await _run(replay_scope())

    assert gateway.paths() == []
    assert failure is not None and failure.code == CLASSIFICATION_UNSUPPORTED
    assert not [p for p in payloads if isinstance(p, CostUsageData)]
