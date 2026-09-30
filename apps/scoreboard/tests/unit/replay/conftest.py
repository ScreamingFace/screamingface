"""Fixtures of the SB-grants tests (E14, OME-1307).

D5: production runs `cloudflare_headers`, so the main path fixtures (`grant_cf_*`) run in that
mode and every call sends `as_user(...)`. The `disabled` fixtures (`grant_app`, `grant_client`)
serve only the fallback test RP-2a.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncGenerator, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, NamedTuple

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, ReportedResult
from tests.unit.submissions._receipts import (
    URL4_A,
    ReceiptKey,
    make_receipt,
    new_receipt_key,
    post_score,
)

FIXED_NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
GRANT_KID = "sb-test-1"


class GrantKey(NamedTuple):
    kid: str
    private_b64: str
    public_key: Ed25519PublicKey


class Seeded(NamedTuple):
    head_id: str
    result_id: str
    cache_version_id: str | None


class SpySigner:
    """A `GrantSigner` that records each call and signs like the real one."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[Mapping[str, object]] = []

    def sign(self, claims: Mapping[str, object]) -> str:
        self.calls.append(dict(claims))
        return str(self._inner.sign(claims))


@pytest.fixture
def grant_key() -> GrantKey:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return GrantKey(GRANT_KID, base64.b64encode(raw).decode(), key.public_key())


@pytest.fixture
def receipt_key() -> ReceiptKey:
    return new_receipt_key()


def grant_settings(grant_key: GrantKey, receipt_key: ReceiptKey, **extra: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "sqlite://:memory:",
        "cors_origins": [],
        "clustering_enabled": True,
        "receipt_public_keys": {receipt_key.kid: receipt_key.public_b64},
        "replay_grant_signing_key": grant_key.private_b64,
        "replay_grant_signing_kid": grant_key.kid,
    }
    values.update(extra)
    return Settings.model_validate(values)


async def _seed_benchmarks() -> None:
    await Benchmark.create(id="pub", display_name="Pub", redistributable=True)
    await Benchmark.create(id="gated", display_name="Gated", redistributable=False)
    await Benchmark.create(id="priv", display_name="Priv", visibility="private")
    await Benchmark.create(id="other", display_name="Other", redistributable=True)


def _pin_clock(app: FastAPI) -> None:
    app.state.clock = lambda: FIXED_NOW


@pytest_asyncio.fixture
async def grant_cf_app(
    tortoise_db: None,
    partial_unique_indexes: None,
    monkeypatch: pytest.MonkeyPatch,
    grant_key: GrantKey,
    receipt_key: ReceiptKey,
) -> FastAPI:
    # WHY FORWARDED_ALLOW_IPS is pinned: ASGITransport reports the peer 127.0.0.1, which is this
    # fixture's `allowed_networks`, and `create_app` refuses a FORWARDED_ALLOW_IPS that overlaps
    # it. The value must be disjoint (same reasoning as `app_with_cloudflare_auth` in
    # tests/unit/test_scores_routes.py).
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    # model_validate, not the constructor: `allowed_networks` arrives as a comma-separated string,
    # as the environment supplies it.
    settings = grant_settings(
        grant_key,
        receipt_key,
        auth_mode="cloudflare_headers",
        allowed_networks="127.0.0.1/32",
    )
    app = create_app(settings)
    _pin_clock(app)
    await _seed_benchmarks()
    return app


@pytest_asyncio.fixture
async def grant_cf_client(grant_cf_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=grant_cf_app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def grant_untrusted_client(grant_cf_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    # A peer outside `allowed_networks` (127.0.0.1/32): the 403 "untrusted peer" path.
    async with AsyncClient(
        transport=ASGITransport(app=grant_cf_app, client=("203.0.113.5", 443)),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def grant_app(
    tortoise_db: None,
    partial_unique_indexes: None,
    grant_key: GrantKey,
    receipt_key: ReceiptKey,
) -> FastAPI:
    """The `disabled` dev/local fallback (D5). Only RP-2a uses it."""
    app = create_app(grant_settings(grant_key, receipt_key))
    _pin_clock(app)
    await _seed_benchmarks()
    return app


@pytest_asyncio.fixture
async def grant_client(grant_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=grant_app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def spy(grant_cf_app: FastAPI) -> SpySigner:
    """The signer of `grant_cf_app`, wrapped: a test reads how many grants were signed."""
    spy_signer = SpySigner(grant_cf_app.state.grant_signer)
    grant_cf_app.state.grant_signer = spy_signer
    return spy_signer


SeedResult = Callable[..., "Any"]


@pytest.fixture
def seed_result(grant_cf_client: AsyncClient, receipt_key: ReceiptKey) -> SeedResult:
    """Submit through `POST /v1/scores`, so the rows are what the real flow makes.

    `reporter` is the verified email of the caller. `receipt=False` submits a run with no cache
    version. `submitted_at` rewrites the result's time afterwards (test data only).
    """

    async def _seed(
        *,
        benchmark: str = "pub",
        reporter: str,
        url4: str = URL4_A,
        score: float = 0.75,
        submitted_at: datetime | None = None,
        receipt: bool = True,
        **overrides: Any,
    ) -> Seeded:
        vid = str(uuid.uuid4()) if receipt else None
        token = make_receipt(receipt_key, sub=reporter, vid=vid) if receipt else None
        response = await post_score(
            grant_cf_client,
            user=reporter,
            receipt=token,
            benchmark_id=benchmark,
            url4_expression=url4,
            score=score,
            **overrides,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        result_id = body["reported_result"]["id"]
        if submitted_at is not None:
            await ReportedResult.filter(id=result_id).update(submitted_at=submitted_at)
        return Seeded(body["id"], result_id, vid)

    return _seed
