"""Fixtures of the SB-publish tests (E14, OME-1307).

D5: production runs `cloudflare_headers`, so the main path fixtures (`publish_*`) run in that mode
and every call sends `as_user(...)`. `publish_disabled_client` serves only the two fallback tests
PB-2a and PB-12a.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.core.publish.ports import ArchivePair
from scoreboard.main import create_app
from scoreboard.publish.worker import PublishWorker
from scoreboard.scores.models import Benchmark
from scoreboard.scores.publication_store import PublicationStore
from tests.unit.publish._fakes import (
    Clock,
    FakeArchiveReader,
    FakeReleasePublisher,
    Seeded,
    canonical_pair,
    pair_sha,
)
from tests.unit.submissions._receipts import (
    ANA,
    ReceiptKey,
    make_receipt,
    new_receipt_key,
    post_score,
)

ADMIN = "admin@x.org"


@pytest.fixture
def receipt_key() -> ReceiptKey:
    return new_receipt_key()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def fake_publisher() -> FakeReleasePublisher:
    return FakeReleasePublisher()


async def _seed_benchmarks() -> None:
    await Benchmark.create(id="pub", display_name="Pub", redistributable=True)
    await Benchmark.create(id="gated", display_name="Gated", redistributable=False)
    await Benchmark.create(id="priv", display_name="Priv", visibility="private")


def _settings(tmp_path: Path, receipt_key: ReceiptKey, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "sqlite://:memory:",
        "cors_origins": [],
        "auth_mode": "cloudflare_headers",
        "allowed_networks": "127.0.0.1/32",
        "clustering_enabled": True,
        "receipt_public_keys": {receipt_key.kid: receipt_key.public_b64},
        "admin_emails": ADMIN,
        "github_app_id": "12345",
        "github_app_installation_id": "678",
        "github_app_private_key": "not-a-real-key",
        "archive_backend": "filesystem",
        "archive_fs_root": tmp_path,
        # WHY off: the tests drive `PublishWorker.run_once` by hand.
        "publish_worker_enabled": False,
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest_asyncio.fixture
async def publish_app(
    tortoise_db: None,
    partial_unique_indexes: None,
    monkeypatch: pytest.MonkeyPatch,
    receipt_key: ReceiptKey,
    tmp_path: Path,
    clock: Clock,
    fake_publisher: FakeReleasePublisher,
) -> FastAPI:
    # WHY FORWARDED_ALLOW_IPS is pinned: ASGITransport reports the peer 127.0.0.1, which is this
    # fixture's `allowed_networks`, and `create_app` refuses a FORWARDED_ALLOW_IPS that overlaps
    # it (same reasoning as `app_with_cloudflare_auth` in tests/unit/test_scores_routes.py).
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    app = create_app(_settings(tmp_path, receipt_key))
    app.state.release_publisher_factory = fake_publisher.factory()
    app.state.clock = clock
    await _seed_benchmarks()
    return app


@pytest_asyncio.fixture
async def publish_client(publish_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=publish_app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def publish_untrusted_client(publish_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    # A peer outside `allowed_networks` (127.0.0.1/32): the 403 "untrusted peer" path.
    async with AsyncClient(
        transport=ASGITransport(app=publish_app, client=("203.0.113.5", 443)),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def publish_disabled_client(
    tortoise_db: None,
    partial_unique_indexes: None,
    receipt_key: ReceiptKey,
    tmp_path: Path,
    fake_publisher: FakeReleasePublisher,
) -> AsyncGenerator[AsyncClient, None]:
    """The `disabled` dev/local fallback (D5): PB-2a and PB-12a only."""
    settings = _settings(tmp_path, receipt_key, auth_mode="disabled", allowed_networks="")
    app = create_app(settings)
    app.state.release_publisher_factory = fake_publisher.factory()
    await _seed_benchmarks()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def unconfigured_client(
    tortoise_db: None,
    partial_unique_indexes: None,
    monkeypatch: pytest.MonkeyPatch,
    receipt_key: ReceiptKey,
) -> AsyncGenerator[AsyncClient, None]:
    """`cloudflare_headers` with no GitHub App and no archive backend: PB-19."""
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def no_admin_client(
    tortoise_db: None,
    partial_unique_indexes: None,
    monkeypatch: pytest.MonkeyPatch,
    receipt_key: ReceiptKey,
    tmp_path: Path,
) -> AsyncGenerator[AsyncClient, None]:
    """`cloudflare_headers` with an empty admin allowlist: the admin routes answer 503."""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    # WHY no seeding: the test also uses `publish_client`, and both share one database.
    app = create_app(_settings(tmp_path, receipt_key, admin_emails=""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def seed_result(
    receipt_key: ReceiptKey,
) -> Callable[..., Awaitable[Seeded]]:
    """Seed one result through `POST /v1/scores`, with a receipt whose `sha` is the pair digest."""

    async def _seed(
        client: AsyncClient,
        *,
        board: str = "pub",
        user: str = ANA,
        pair: ArchivePair | None = None,
        with_receipt: bool = True,
    ) -> Seeded:
        the_pair = pair if pair is not None else canonical_pair()
        version_id = uuid.uuid4()
        receipt = (
            make_receipt(receipt_key, sub=user, vid=str(version_id), sha=pair_sha(the_pair))
            if with_receipt
            else None
        )
        response = await post_score(client, user=user, benchmark_id=board, receipt=receipt)
        assert response.status_code == 201, response.text
        body = response.json()
        return Seeded(
            head_id=body["id"],
            result_id=body["reported_result"]["id"],
            version_id=version_id,
            pair=the_pair,
        )

    return _seed


@pytest.fixture
def build_worker(
    publish_app: FastAPI, fake_publisher: FakeReleasePublisher, clock: Clock
) -> Callable[..., PublishWorker]:
    def _build(seeded: Seeded, reader: FakeArchiveReader | None = None) -> PublishWorker:
        store: PublicationStore = publish_app.state.publication_store
        return PublishWorker(
            store=store,
            publisher_factory=fake_publisher.factory(),
            archive_reader=reader or FakeArchiveReader({seeded.version_id: seeded.pair}),
            facts_loader=store.release_facts,
            metrics=publish_app.state.metrics,
            clock=clock,
            rng=lambda: 0.0,
        )

    return _build
