"""Proves the FORWARDED_ALLOW_IPS/allowed_networks overlap guard (main.py) actually holds once
wired through a REAL uvicorn ProxyHeadersMiddleware — not just that `create_app` raises on a bad
config. No other test in this suite constructs a real `ProxyHeadersMiddleware`-wrapped app; every
other route test calls `create_app()` directly via `TestClient`/`ASGITransport`, bypassing that
middleware entirely (it's applied by uvicorn's own `Config`/server around the
`"scoreboard.main:app"` string target in `cli.py`, never inside `create_app()` itself). This is
the only test that proves `main.py`'s independent `_TrustedHosts`-mirroring classification and
uvicorn's real one actually agree once wired together the way production does.

WHY this test, not a "vulnerable but running" reproduction: main.py's overlap guard (see
test_allowed_networks.py) already prevents an overlapping configuration from starting at all — a
test trying to prove the OLD bug would just hit that guard's ValueError, which is redundant with
tests that already exist there. The valuable, non-redundant case is the ALLOWED (disjoint)
configuration: proving a forged X-Forwarded-For from a peer OUTSIDE FORWARDED_ALLOW_IPS's trusted
set is correctly ignored by the real middleware, so peer_in_networks() still sees the genuine,
untrusted peer.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.routes.scores import UNTRUSTED_PEER_DETAIL

pytestmark = pytest.mark.asyncio

# RFC 5737 TEST-NET ranges — never real, routable addresses.
TRUSTED_PROXY_PEER = ("192.0.2.1", 443)  # TEST-NET-1: the mesh peer FORWARDED_ALLOW_IPS trusts
UNTRUSTED_PEER = ("203.0.113.5", 443)  # TEST-NET-3: connects directly, outside every trusted set


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_id": "hle",
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "score": 0.75,
        "total_questions": 4,
        "correct_questions": 3,
        "ran_with_providers": ["openai"],
        "run_cost_usd": "1.250000",
    }
    payload.update(overrides)
    return payload


@pytest_asyncio.fixture
async def proxy_wrapped_app(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> ProxyHeadersMiddleware:
    # WHY disjoint from allowed_networks below: this fixture models the CORRECT, allowed
    # configuration (main.py's overlap guard must let this start) — TRUSTED_PROXY_PEER is the
    # mesh peer FORWARDED_ALLOW_IPS legitimately trusts, deliberately outside allowed_networks.
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", TRUSTED_PROXY_PEER[0])
    settings = Settings.model_validate(
        {
            "database_url": "sqlite://:memory:",
            "cors_origins": [],
            "auth_mode": "cloudflare_headers",
            "allowed_networks": "10.0.0.0/8",
        }
    )
    app = create_app(settings)  # must succeed: FORWARDED_ALLOW_IPS is disjoint from 10.0.0.0/8
    # WHY cast: same cross-library ASGI stub-typing seam as untrusted_peer_client's cast below
    # (uvicorn._types vs starlette.types Scope/Receive) — FastAPI's app is a real ASGI3
    # callable at runtime, just not nominally typed as uvicorn's own stub expects.
    return ProxyHeadersMiddleware(cast(Any, app), trusted_hosts=TRUSTED_PROXY_PEER[0])


@pytest_asyncio.fixture
async def untrusted_peer_client(
    proxy_wrapped_app: ProxyHeadersMiddleware,
) -> AsyncGenerator[AsyncClient, None]:
    # WHY cast: uvicorn's ProxyHeadersMiddleware and httpx's ASGITransport each declare their
    # own Scope/Receive/Send stub types (uvicorn._types vs starlette.types) — structurally
    # identical ASGI callables at runtime, but pyright treats them as nominally incompatible
    # across the two packages. Nothing to fix on either side; this is the cross-library ASGI
    # stub-typing seam, not a real type error.
    async with AsyncClient(
        transport=ASGITransport(app=cast(Any, proxy_wrapped_app), client=UNTRUSTED_PEER),
        base_url="http://test",
    ) as client:
        yield client


async def test_forged_x_forwarded_for_from_an_untrusted_peer_is_ignored(
    untrusted_peer_client: AsyncClient,
) -> None:
    """UNTRUSTED_PEER did not connect through the trusted proxy, so real ProxyHeadersMiddleware
    must leave request.client.host alone — peer_in_networks() then correctly rejects it as
    untrusted, never reaching the forged X-User-Email. If this ever passed with a 201/200, the
    overlap guard and uvicorn's real behavior have drifted apart despite this fixture's disjoint
    configuration, and something is very wrong.
    """
    response = await untrusted_peer_client.post(
        "/v1/scores",
        json=_valid_payload(),
        headers={
            "X-Forwarded-For": "10.0.0.5",  # inside allowed_networks — the forgery attempt
            "X-User-Email": "attacker@evil.example",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == UNTRUSTED_PEER_DETAIL
