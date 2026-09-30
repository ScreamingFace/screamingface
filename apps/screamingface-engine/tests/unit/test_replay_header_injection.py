"""E14 (RP-12) — no inbound value can set or displace the run's replay header.

FEATURE: reproducible submissions (OME-1307). The replay header is gateway-owned: a run that
holds no grant must send none, and a run that holds one must send exactly that one.

INVARIANT (RP-D2): `RequestScope.identity_headers` reaches the connector from an inbound request,
and nothing guarantees the mapping holds ONLY the identity key. The connector therefore drops any
replay-named key from it and writes the run's own grant LAST, as it does `X-Profile`.

INVARIANT: the gateway-named header is never read from the start request. Only the SDK-facing
`X-SF-Cache-Replay` carries a grant into the engine.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.job_env import RunShape
from screamingface_engine.ports import ReplayAwareJobRunner
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run
from url4.streaming.protocol import CachePolicy

SECRET = "replay-injection-unit-secret"
WINDOW_S = 60
LIFETIME_S = 58_800
T0 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)
MODEL = "anthropic/claude-haiku-4-5"
GRANT = "eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0.eyJ2aWQiOiJ2In0.c2ln"
IDENTITY = {"X-User-Email": "someone@openmined.org"}
_GATEWAY_HEADER = "x-aigw-cache-replay"


async def _outbound_requests(scope: RequestScope) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    cfg = AigatewayConfig(models=(ModelSpec(id=MODEL),), default_model=MODEL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(cfg, client=client)
        with request_scope(scope):
            await url4_run(f"/{MODEL}('ctx')!'go'", world.node)
    return seen


@pytest.mark.asyncio
async def test_an_identity_mapping_cannot_set_the_replay_header() -> None:
    scope = RequestScope(
        origin="run",
        identity_headers={**IDENTITY, "x-aigw-cache-replay": "forged"},
    )

    requests = await _outbound_requests(scope)

    assert len(requests) == 1
    assert _GATEWAY_HEADER not in requests[0].headers
    assert requests[0].headers["X-User-Email"] == IDENTITY["X-User-Email"]


@pytest.mark.asyncio
async def test_an_identity_mapping_cannot_displace_the_runs_grant() -> None:
    scope = RequestScope(
        origin="run",
        replay_grant=GRANT,
        identity_headers={**IDENTITY, "X-AIGW-Cache-Replay": "forged"},
    )

    requests = await _outbound_requests(scope)

    assert requests[0].headers.get_list(_GATEWAY_HEADER) == [GRANT]


class _GrantRecordingRunner(RecordingJobRunner, ReplayAwareJobRunner):
    def __init__(self) -> None:
        super().__init__()
        self.replay_grants: list[str | None] = []

    async def schedule(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        credential: str | None = None,
        profile: str | None = None,
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
        answer_seed: int | None = None,
        client_version: str | None = None,
        shape: RunShape = "expression",
        replay_grant: str | None = None,
    ) -> str:
        self.replay_grants.append(replay_grant)
        return await super().schedule(
            topic, url4, deadline_s, traceparent=traceparent, identity=identity
        )


@pytest.mark.asyncio
async def test_an_inbound_gateway_header_on_get_is_never_carried() -> None:
    runner = _GrantRecordingRunner()
    app = create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=InMemoryEventStream(),
        job_runner=runner,
        clock=lambda: T0,
        interest=FixedGate(),
    )
    token = JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(
        "injection-get", T0
    )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={
                "URL4-Capability": token,
                "Prefer": "respond-async",
                "X-AIGW-Cache-Replay": "forged",
            },
        )

    assert resp.status_code == 202
    assert runner.replay_grants == [None]
