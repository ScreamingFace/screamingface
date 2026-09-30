"""E14 (RP-13) — the engine counts the gateway's version hits and misses into the run's report.

FEATURE: reproducible submissions (OME-1307). A replay run's every chat call carries the grant;
the gateway answers each with `X-AIGW-Cache-Version: hit|miss`. The run tallies those answers and
publishes them on its ONE closing cache-summary frame as `cache.version.hits`,
`cache.version.misses` and `cache.version.repeated_key_collapses`, so the SDK can state how much
of a replay the version actually served.

INVARIANT: a plain run publishes no `cache.version.*` key — its frames are byte-identical to
today's.

INVARIANT (RP-H1): a call the version holds is served from the version. A version hit is exempt
from `max-age` revalidation, because a revalidation re-issue would discard the pinned answer and
go live.
"""

from __future__ import annotations

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope
from screamingface_engine.runner.cache_counters import (
    CACHE_HITS,
    VERSION_HITS,
    VERSION_MISSES,
    VERSION_REPEATED_KEY_COLLAPSES,
)
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.streaming.interfaces import Completed, Traced
from url4.streaming.protocol import CachePolicy, LogData

MODEL = "anthropic/claude-haiku-4-5"
GRANT = "eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0.eyJ2aWQiOiJ2In0.c2ln"
THREE_CALLS = f"/{MODEL}(/{MODEL}(/{MODEL}('a')!'x')!'y')!'z'"
_VERSION_HIT = {
    "Cache-Status": "aigateway; hit; detail=version",
    "X-AIGW-Cache-Version": "hit",
}
_VERSION_MISS = {"X-AIGW-Cache": "miss", "X-AIGW-Cache-Version": "miss"}


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


async def _frames(
    gateway: _Gateway, expression: str, *, scope: RequestScope | None = None
) -> list[object]:
    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with gateway.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        executor = Url4Executor(
            world.node,
            request_scope_factory=lambda: scope or RequestScope(origin="run", replay_grant=GRANT),
        )
        return [frame async for frame in executor.execute(expression)]


def _summaries(frames: list[object], key: str) -> list[LogData]:
    payloads = [f.payload if isinstance(f, Traced) else f for f in frames]
    return [p for p in payloads if isinstance(p, LogData) and key in p.attributes]


@pytest.mark.asyncio
async def test_engine_counts_version_hits_and_misses_into_report() -> None:
    gateway = _Gateway([_VERSION_HIT, _VERSION_HIT, _VERSION_MISS])

    frames = await _frames(gateway, THREE_CALLS)

    assert isinstance(frames[-1], Completed)
    summaries = _summaries(frames, VERSION_HITS)
    assert len(summaries) == 1
    attributes = summaries[0].attributes
    assert attributes[VERSION_HITS] == 2
    assert attributes[VERSION_MISSES] == 1
    # The answers name no entry key, so no hit can be a repeat of another.
    assert attributes[VERSION_REPEATED_KEY_COLLAPSES] == 0
    assert all(type(attributes[k]) is int for k in (VERSION_HITS, VERSION_MISSES))
    assert type(attributes[VERSION_REPEATED_KEY_COLLAPSES]) is int
    assert all(GRANT not in str(value) for value in attributes.values())


@pytest.mark.asyncio
async def test_a_plain_run_publishes_no_version_keys() -> None:
    gateway = _Gateway([{"X-AIGW-Cache": "hit", "X-AIGW-Cache-Reason": "fresh"}])

    frames = await _frames(gateway, f"/{MODEL}('ctx')!'go'", scope=RequestScope(origin="run"))

    summary = _summaries(frames, CACHE_HITS)
    assert len(summary) == 1
    assert not any(key.startswith("cache.version.") for key in summary[0].attributes)
    assert "cache version" not in summary[0].body


@pytest.mark.asyncio
async def test_a_version_hit_is_not_revalidated_under_max_age() -> None:
    # A hit with no `Age` under `max-age` is re-issued as an opt-out for any other hit; a version
    # hit is the pinned answer, so exactly ONE request may reach the gateway.
    gateway = _Gateway([_VERSION_HIT])
    scope = RequestScope(
        origin="run",
        replay_grant=GRANT,
        cache=CachePolicy(participate=True, max_age=60),
    )

    frames = await _frames(gateway, f"/{MODEL}('ctx')!'go'", scope=scope)

    assert isinstance(frames[-1], Completed)
    assert len(gateway.requests) == 1
