"""SYN-10: a sync `GET /?q=` with no WebSocket, end to end on a real JetStream (PRD 02).

The App's real consumer reads the shared events stream; a stand-in child (the mock run through
the real `JetStreamPublisher`) writes the run's frames once the App schedules it.
"""

import asyncio
import os
import socket
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport

from screamingface_engine.adapters.jetstream import JetStreamConsumer, JetStreamPublisher
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing.mock_runner import publish_mock_run

NATS_URL = os.environ.get("URL4_CLOUD_TEST_NATS_URL", "nats://localhost:4222")
SECRET = "sync-without-ws-secret"
T0 = datetime(2026, 9, 25, 9, 0, 0, tzinfo=UTC)


def _nats_reachable(url: str = NATS_URL) -> bool:
    parsed = urlsplit(url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 4222), 0.5):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not _nats_reachable(), reason=f"needs a reachable NATS at {NATS_URL}"),
]


class _MockChildRunner:
    """Schedules a run by starting the mock run's publisher, as a worker's child would."""

    def __init__(self) -> None:
        self.children: list[asyncio.Task[None]] = []

    async def schedule(self, topic: str, url4: str, deadline_s: int, **kwargs: Any) -> str:
        async def child() -> None:
            publisher = JetStreamPublisher(NATS_URL)
            try:
                await publish_mock_run(publisher, topic, url4)
                await publisher.flush()
            finally:
                await publisher.close()

        self.children.append(asyncio.ensure_future(child()))
        return f"job-{topic}"

    async def stop(self, topic: str) -> None:
        return None

    async def exists(self, topic: str) -> bool:
        return False

    async def status(self, topic: str) -> str:
        return "running"


async def test_sync_without_ws_end_to_end_on_real_nats() -> None:
    topic = f"syn10-{uuid4().hex}"
    token = JwtCodec(secret=SECRET, iat_window_s=60, capability_lifetime_s=58_800).sign(topic, T0)
    runner = _MockChildRunner()
    consumer = JetStreamConsumer(NATS_URL)
    app = create_app(
        Settings(jwt_secret=SECRET, iat_window_s=60, sync_max_wait_s=10.0),
        stream=consumer,
        job_runner=runner,  # type: ignore[arg-type]
        clock=lambda: T0,
    )
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/", params={"q": "(gpt,claude)!'hi'"}, headers={"URL4-Capability": token}
            )
        assert resp.status_code == 200
        assert resp.text == "[mock] done"
        assert app.state.registry.sync_holders == 0
        await asyncio.gather(*runner.children)
    finally:
        await consumer.close()
