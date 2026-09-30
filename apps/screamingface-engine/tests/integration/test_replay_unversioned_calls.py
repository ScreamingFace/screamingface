"""E14 (RP-13e) — a replay call the gateway answers with NO version header still counts.

FEATURE: reproducible submissions (OME-1307). A gateway that does not honour the grant (an old or
mixed replica during the rollout, or a path that drops the header) answers 2xx with no
`X-AIGW-Cache-Version`. That call went to the live provider, so it is a version MISS (C12).

INVARIANT (RP-E6, RP-H5): a replay never becomes a live run in silence. A grant-carrying call the
version did not serve is counted, so the closing frame shows `cache.version.misses > 0` and the SDK
cannot read a partly live replay as complete.
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
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.protocol import LogData

MODEL = "anthropic/claude-haiku-4-5"
GRANT = "eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0.eyJ2aWQiOiJ2In0.c2ln"
THREE_CALLS = f"/{MODEL}(/{MODEL}(/{MODEL}('a')!'x')!'y')!'z'"
_VERSION_HIT = {
    "Cache-Status": "aigateway; hit; detail=version",
    "X-AIGW-Cache-Version": "hit",
}
_NO_VERSION_HEADER = {"X-AIGW-Cache": "miss"}


class _Gateway:
    """A chat-completions endpoint that answers call N with the Nth header set."""

    def __init__(self, answers: list[dict[str, str]]) -> None:
        self._answers = answers
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        index = len(self.requests)
        self.requests.append(request)
        return httpx.Response(
            200,
            headers=self._answers[min(index, len(self._answers) - 1)],
            json={
                "choices": [{"message": {"role": "assistant", "content": "an answer"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )


async def _frames(gateway: _Gateway, expression: str) -> list[object]:
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gateway.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(
            world.node,
            request_scope_factory=lambda: RequestScope(origin="run", replay_grant=GRANT),
        )
        return [frame async for frame in executor.execute(expression)]


def _summaries(frames: list[object]) -> list[LogData]:
    payloads = [f.payload if isinstance(f, Traced) else f for f in frames]
    return [p for p in payloads if isinstance(p, LogData) and VERSION_HITS in p.attributes]


@pytest.mark.asyncio
async def test_a_grant_call_with_no_version_header_counts_as_a_version_miss() -> None:
    gateway = _Gateway([_VERSION_HIT, _NO_VERSION_HEADER, _NO_VERSION_HEADER])

    frames = await _frames(gateway, THREE_CALLS)

    assert isinstance(frames[-1], Completed)
    assert len(gateway.requests) == 3
    summaries = _summaries(frames)
    assert len(summaries) == 1
    attributes = summaries[0].attributes
    assert attributes[VERSION_HITS] == 1
    assert attributes[VERSION_MISSES] == 2
    assert attributes[VERSION_REPEATED_KEY_COLLAPSES] == 0


@pytest.mark.asyncio
async def test_a_grant_run_whose_calls_all_lack_the_version_header_still_publishes_all_three() -> (
    None
):
    gateway = _Gateway([_NO_VERSION_HEADER])

    frames = await _frames(gateway, f"/{MODEL}('ctx')!'go'")

    summaries = _summaries(frames)
    assert len(summaries) == 1
    attributes = summaries[0].attributes
    assert attributes[VERSION_HITS] == 0
    assert attributes[VERSION_MISSES] == 1
    assert attributes[VERSION_REPEATED_KEY_COLLAPSES] == 0
