"""Fixtures of the SB-submit tests (E14, OME-1307).

D5: production runs `cloudflare_headers`, so the main path fixtures (`clustered_cf_*`) run in that
mode and every call sends `as_user(...)`. The `disabled` fixtures (`clustered_*`) serve only the
fallback tests SC-1, SC-2, SC-8a and SC-17b.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark
from tests.unit.submissions._receipts import ReceiptKey, make_receipt, new_receipt_key


@pytest.fixture
def receipt_key() -> ReceiptKey:
    return new_receipt_key()


@pytest.fixture
def sign_receipt(receipt_key: ReceiptKey) -> Callable[..., str]:
    def _sign(**overrides: Any) -> str:
        return make_receipt(receipt_key, **overrides)

    return _sign


async def _seed_benchmarks() -> None:
    await Benchmark.create(id="pub", display_name="Pub", redistributable=True)
    await Benchmark.create(id="gated", display_name="Gated", redistributable=False)
    await Benchmark.create(id="priv", display_name="Priv", visibility="private")


@pytest_asyncio.fixture
async def clustered_cf_app(
    tortoise_db: None,
    partial_unique_indexes: None,
    monkeypatch: pytest.MonkeyPatch,
    receipt_key: ReceiptKey,
) -> FastAPI:
    # WHY FORWARDED_ALLOW_IPS is pinned: ASGITransport reports the peer 127.0.0.1, which is this
    # fixture's `allowed_networks`, and `create_app` refuses a FORWARDED_ALLOW_IPS that overlaps
    # it. The value must be disjoint (same reasoning as `app_with_cloudflare_auth` in
    # tests/unit/test_scores_routes.py).
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    settings = Settings.model_validate(
        {
            "database_url": "sqlite://:memory:",
            "cors_origins": [],
            "auth_mode": "cloudflare_headers",
            "allowed_networks": "127.0.0.1/32",
            "clustering_enabled": True,
            "receipt_public_keys": {receipt_key.kid: receipt_key.public_b64},
        }
    )
    app = create_app(settings)
    await _seed_benchmarks()
    return app


@pytest_asyncio.fixture
async def clustered_cf_client(clustered_cf_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=clustered_cf_app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def clustered_untrusted_client(
    clustered_cf_app: FastAPI,
) -> AsyncGenerator[AsyncClient, None]:
    # A peer outside `allowed_networks` (127.0.0.1/32): the 403 "untrusted peer" path.
    async with AsyncClient(
        transport=ASGITransport(app=clustered_cf_app, client=("203.0.113.5", 443)),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def clustered_app(
    tortoise_db: None, partial_unique_indexes: None, receipt_key: ReceiptKey
) -> FastAPI:
    """The `disabled` dev/local fallback (D5). Only SC-1, SC-2, SC-8a and SC-17b use it."""
    settings = Settings(
        database_url="sqlite://:memory:",
        cors_origins=[],
        clustering_enabled=True,
        receipt_public_keys={receipt_key.kid: receipt_key.public_b64},
    )
    app = create_app(settings)
    await _seed_benchmarks()
    return app


@pytest_asyncio.fixture
async def clustered_client(clustered_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=clustered_app), base_url="http://test"
    ) as client:
        yield client
