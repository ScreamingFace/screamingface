"""A mount call names a broker outage as an outage, not as capacity (design review).

`rest/mounts.py` rewrites every 503 from `_schedule` into url4's `overloaded` shed envelope. That
code is the only 503 shape url4 clients know, so it is kept; but the MESSAGE is chosen by cause —
"server at capacity" for a full queue, "the run queue is unavailable" for an unreachable broker.
Both keep the `Retry-After` the REST edge set.
"""

from typing import Any

import httpx
import pytest
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.rest.mounts import register_mounts
from screamingface_engine.runner_queue import RunQueueUnavailable
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.serving import MountDescriptor, MountTable
from url4.streaming.interfaces import JobRunnerAtCapacity

pytestmark = pytest.mark.asyncio

TABLE = MountTable(
    mounts=(MountDescriptor("/v1/chat/completions", "endpoint", None),), config_digest="abc"
)
EMAIL = {"X-User-Email": "caller@example.com"}


class _Refusing:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def schedule(self, topic: str, url4: str, deadline_s: int, **kwargs: Any) -> str:
        raise self._error

    async def stop(self, topic: str) -> None:
        pass

    async def exists(self, topic: str) -> bool:
        return False

    async def status(self, topic: str) -> str:
        return "running"


async def _call(error: Exception) -> httpx.Response:
    app = create_app(
        Settings(jwt_secret="mount-secret-0123456789abcdef0123"),
        stream=InMemoryEventStream(),
        job_runner=_Refusing(error),  # type: ignore[arg-type]
    )
    register_mounts(app, TABLE)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/v1/chat/completions?q=(a)!b", headers=EMAIL)


async def test_a_broker_outage_is_not_reported_as_capacity() -> None:
    resp = await _call(RunQueueUnavailable("down"))

    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "5"
    error = resp.json()["error"]
    assert error["code"] == "overloaded"
    assert error["message"] == "the run queue is unavailable, retry shortly"


async def test_a_full_queue_is_still_reported_as_capacity() -> None:
    resp = await _call(JobRunnerAtCapacity(4, 4, retry_after_s=42))

    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "42"
    assert resp.json()["error"]["message"] == "server at capacity, retry shortly"
