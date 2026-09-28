"""The uniform path, end to end (uniform executor PRD 04, K3-lite): a mount call on the REAL App
becomes a direct run on the REAL queue, a REAL worker hands it to a REAL warm `run --warm` child,
which builds the declared world, runs the ONE data route, and publishes the frames the App
answers from.

Linux-only: the worker spawns through the exec wrapper, whose `RLIMIT_AS` macOS refuses.
"""

import asyncio
import os
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport

from screamingface_engine import job_env
from screamingface_engine.adapters.factory import build_job_runner
from screamingface_engine.adapters.jetstream import JetStreamConsumer, JetStreamPublisher
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.rest.mounts import register_mounts
from screamingface_engine.runner_queue import RunQueue
from screamingface_engine.worker.loop import Worker
from screamingface_engine.world.serving import derive_mount_table, engine_route_paths

NATS_URL = os.environ.get("URL4_CLOUD_TEST_NATS_URL", "nats://localhost:4222")


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
    pytest.mark.skipif(
        sys.platform != "linux", reason="the exec wrapper's RLIMIT_AS is Linux-only"
    ),
]

_WORLD = (
    "[aigateway]\n"
    'base_url = "http://aigateway.invalid"\n'
    'default_route = "/anthropic/claude-haiku-4-5"\n'
    "\n[data]\n"
    '"/corpus/papers" = { value = "rows of papers", media_type = "text/plain" }\n'
)


async def test_a_mount_call_runs_as_a_direct_run_on_a_warm_worker_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, runner, consumer, queue, publisher, worker = await _stack(tmp_path, monkeypatch)
    assert worker._pool is not None  # noqa: SLF001
    try:
        worker._pool.start()  # noqa: SLF001
        async with asyncio.TaskGroup() as tg:
            claim = tg.create_task(worker._claim_loop(tg))  # noqa: SLF001
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await asyncio.wait_for(
                    client.get("/corpus/papers", headers={"X-User-Email": "c@x"}), timeout=60
                )
                eval_path = await client.get("/v1?q=(a)!b", headers={"X-User-Email": "c@x"})
            claim.cancel()
    finally:
        await worker._pool.drain()  # noqa: SLF001
        await consumer.close()
        await publisher.close()
        await queue.close()
        aclose = getattr(runner, "aclose", None)
        if aclose is not None:
            await aclose()
    assert resp.status_code == 200, resp.text
    assert resp.text == "rows of papers"
    assert resp.headers["content-type"].startswith("text/plain")
    assert eval_path.status_code == 404  # MC-E2: no route; nothing queued


async def _stack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    """The real App (mounts registered from the declared world) and a real worker."""
    world = tmp_path / "url4.toml"
    world.write_text(_WORLD)
    # The worker's children inherit these (a warm child reads only per-process keys).
    monkeypatch.setenv(job_env.RUNNER_CONFIG, str(world))
    monkeypatch.setenv(job_env.NATS_URL, NATS_URL)
    # Fresh queue objects per test run: the stream and subject prefix are per-test.
    tag = uuid4().hex[:8]
    settings = Settings(
        jwt_secret="spine-secret-" + "x" * 32,
        runner="queue",
        nats_url=NATS_URL,
        run_queue_stream=f"it-runq-{tag}",
        run_queue_subject_prefix=f"it-runq-{tag}",
        sync_max_wait_s=20.0,
    )
    consumer = JetStreamConsumer(NATS_URL)
    runner = build_job_runner(settings)
    # `runner="none"` for the App's own check only: that check refuses a queue runner with a
    # pod-local artifact store (correct in a cluster); here App and worker share one disk.
    app = create_app(
        settings.model_copy(update={"runner": "none"}), stream=consumer, job_runner=runner
    )
    register_mounts(
        app, await derive_mount_table(env=os.environ, engine_routes=engine_route_paths(app))
    )

    queue = RunQueue(
        NATS_URL,
        stream=settings.run_queue_stream,
        subject_prefix=settings.run_queue_subject_prefix,
        state_cache_ttl_s=0.0,
        replicas=1,
    )
    await queue.ensure_stream()
    publisher = JetStreamPublisher(NATS_URL, writer="supervisor")
    worker = Worker(
        queue=queue,
        publisher=publisher,
        slots=1,
        drain_grace_s=1.0,
        io_capacity=4,
        memory_budget_bytes=2 * 1024**3,
        pull_timeout_s=0.5,
        warm_children=1,
    )
    return app, runner, consumer, queue, publisher, worker
