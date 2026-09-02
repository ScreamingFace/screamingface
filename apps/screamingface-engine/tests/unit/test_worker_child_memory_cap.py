"""The worker's per-child memory cap (OME-1089): each child is spawned under its own
``RLIMIT_AS``, so an over-allocating run dies ALONE instead of triggering a Pod OOM that
kills its co-tenants — which would void the reason for choosing subprocess isolation.

This test spawns REAL children through the worker's actual spawn path (the exec wrapper),
with a fake ``screamingface-engine`` on PATH that allocates past the budget. The wrapper
sets the limit and execs the fake in place, exactly as it would exec the real entrypoint.
"""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.worker.loop import Worker
from screamingface_engine.worker.supervisor import CHILD_EXITED

pytestmark = pytest.mark.asyncio

# 128 MiB of address space: enough for the interpreter to start, far too little for the
# fake runner's 512 MiB allocation. (RLIMIT_AS bounds VIRTUAL address space, which is
# larger than the RSS a cgroup limit measures.)
_BUDGET_BYTES = 128 * 1024 * 1024
_ALLOCATION_BYTES = 512 * 1024 * 1024

_FAKE_RUNNER = f"""#!/usr/bin/env python3
import os
import sys

if os.environ.get("URL4_CLOUD_TOPIC", "").endswith("-oom"):
    # Allocate far past the worker's per-run budget: the RLIMIT_AS the exec wrapper set
    # makes this raise MemoryError, and the child dies alone.
    x = bytearray({_ALLOCATION_BYTES})
sys.exit(0)
"""


def _message(topic: str) -> bytes:
    return json.dumps(
        {
            job_env.TOPIC: topic,
            job_env.EXPRESSION: "'hi'",
            job_env.JOB_DEADLINE_S: "60",
            job_env.STREAM_GRACE_S: "0",
        }
    ).encode()


class _FakeMsg:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.metadata = SimpleNamespace(timestamp=None)
        self.acked = False

    async def ack(self) -> None:
        self.acked = True

    async def in_progress(self) -> None:
        pass


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def last_frame(self, topic: str) -> None:
        return None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _FakeQueue:
    async def pull(self, batch: int, timeout_s: float) -> list[_FakeMsg]:
        await asyncio.sleep(timeout_s)
        return []


async def test_an_over_allocating_child_dies_alone_and_the_worker_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child spawned under a per-run RLIMIT_AS that allocates past it dies alone: the
    worker publishes a named failure for it, its sibling run survives, and the worker
    process itself is untouched."""
    # A fake `screamingface-engine` on PATH: the exec wrapper execs it in place, exactly
    # as it would exec the real entrypoint. The `-oom` topic allocates past the budget;
    # any other topic exits cleanly.
    fake = tmp_path / "screamingface-engine"
    fake.write_text(_FAKE_RUNNER)
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

    publisher = _FakePublisher()
    worker = Worker(
        queue=_FakeQueue(),
        publisher=publisher,
        slots=2,
        drain_grace_s=0.1,
        io_capacity=4,
        memory_budget_bytes=_BUDGET_BYTES,
    )

    oom_msg = _FakeMsg(_message("t-oom"))
    ok_msg = _FakeMsg(_message("t-ok"))
    await worker._supervisor.supervise(oom_msg)
    await worker._supervisor.supervise(ok_msg)

    # The over-allocating run died alone: the worker published a named failure for it.
    # (The child died of a Python-level MemoryError, so the worker classifies it as a
    # non-zero exit — the OS never had to kill it, which is exactly the point of the
    # per-child cap.)
    assert len(publisher.published) == 1
    frame = publisher.published[0]
    assert frame.data.status == "failed"
    assert frame.data.error is not None and frame.data.error.code == CHILD_EXITED
    assert oom_msg.acked
    # ...and the sibling run survived: clean exit, the worker adds nothing.
    assert ok_msg.acked
    # The worker process itself is alive — we are still running, and the supervisor
    # accepted a second run after the first one died.
    assert worker._slots == 2
