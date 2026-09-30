"""E14 (RP-X1) — a grant call that ends non-2xx on the live path counts as a version miss.

FEATURE: reproducible submissions (OME-1307). A replay call the version did not serve falls
through to the live provider. When that live call then fails (a credential error, a provider
4xx or 5xx), the gateway sends no `X-AIGW-Cache-Version` on the error response, and the engine
raises before it reads one. A benchmark may collect that failure as a failed case and finish.

INVARIANT (RP-E6, RP-H5, C12): a replay never reads as complete when a call fell through to the
live provider. A grant-carrying call that ends non-2xx, other than `403 replay_grant_invalid`
(which fails the run), is a version MISS, so the closing frame shows `misses >= 1`.
"""

from __future__ import annotations

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope
from screamingface_engine.runner.cache_counters import (
    VERSION_HITS,
    VERSION_MISSES,
    VERSION_REPEATED_KEY_COLLAPSES,
)
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.peer.server import Request, Url4Node
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.protocol import LogData

MODEL = "anthropic/claude-haiku-4-5"
GRANT = "eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0.eyJ2aWQiOiJ2In0.c2ln"
_VERSION_HIT = {"Cache-Status": "aigateway; hit; detail=version", "X-AIGW-Cache-Version": "hit"}
_OK_BODY = {
    "choices": [{"message": {"role": "assistant", "content": "an answer"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
}


def _answer(status: int) -> httpx.Response:
    if status == 200:
        return httpx.Response(200, headers=_VERSION_HIT, json=_OK_BODY)
    return httpx.Response(status, json={"detail": {"code": "provider_failed", "message": "no"}})


class _Gateway:
    """A chat-completions endpoint that answers call N with the Nth status."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses = statuses
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        index = len(self.requests)
        self.requests.append(request)
        return _answer(self._statuses[min(index, len(self._statuses) - 1)])


async def _run_collecting(
    statuses: list[int], calls: int, *, grant: str | None = GRANT
) -> tuple[list[object], list[str]]:
    """Run `calls` gateway calls in a benchmark case that collects each failure and answers."""
    gateway = _Gateway(statuses)
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    collected: list[str] = []
    frames: list[object] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(gateway._handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(cfg, client=client)
        node = Url4Node("bench", default_processor="/m")

        async def handler(request: Request) -> str:
            for index in range(calls):
                try:
                    await url4_run(f"/{MODEL}('ctx{index}')!'go'", world.node)
                except ResolutionError as exc:
                    collected.append(exc.code)
            return "ok"

        node.endpoint("/m")(handler)
        executor = Url4Executor(
            node, request_scope_factory=lambda: RequestScope(origin="run", replay_grant=grant)
        )
        frames = [frame async for frame in executor.execute("/m('x')!'go'")]
    return frames, collected


def _summaries(frames: list[object]) -> list[LogData]:
    payloads = [f.payload if isinstance(f, Traced) else f for f in frames]
    return [p for p in payloads if isinstance(p, LogData) and VERSION_HITS in p.attributes]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 404, 429, 500, 502])
async def test_a_collected_failed_grant_call_counts_as_a_version_miss(status: int) -> None:
    frames, collected = await _run_collecting([200, status], calls=2)

    assert collected == ["provider_failed"]
    assert isinstance(frames[-1], Completed)
    summaries = _summaries(frames)
    assert len(summaries) == 1
    attributes = summaries[0].attributes
    assert attributes[VERSION_HITS] == 1
    assert attributes[VERSION_MISSES] == 1
    assert attributes[VERSION_REPEATED_KEY_COLLAPSES] == 0


@pytest.mark.asyncio
async def test_a_run_whose_only_grant_call_failed_still_publishes_the_miss() -> None:
    frames, collected = await _run_collecting([500], calls=1)

    assert len(collected) == 1
    assert isinstance(frames[-1], Completed)
    summaries = _summaries(frames)
    assert len(summaries) == 1
    assert summaries[0].attributes[VERSION_HITS] == 0
    assert summaries[0].attributes[VERSION_MISSES] == 1


@pytest.mark.asyncio
async def test_a_failed_call_with_no_grant_counts_nothing() -> None:
    frames, collected = await _run_collecting([200, 500], calls=2, grant=None)

    assert len(collected) == 1
    assert isinstance(frames[-1], Completed)
    # The 200 answer still reports its own version header; the failed call adds no miss.
    attributes = _summaries(frames)[0].attributes
    assert attributes[VERSION_HITS] == 1
    assert attributes[VERSION_MISSES] == 0
