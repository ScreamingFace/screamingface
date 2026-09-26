"""WRM-1 / WC-D3 on the REAL entrypoint: `screamingface-engine run --warm` as a process.

READY on the control pipe (world "error" — no world config exists here), one RUN_SPEC on
stdin, ACK, then the run itself: its own Started and Terminated(failed) on the shared stream,
because the world cannot be built. Then the process exits.
"""

import asyncio
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from screamingface_engine import child_protocol as cp
from screamingface_engine import job_env
from screamingface_engine.adapters.jetstream import JetStreamConsumer
from url4.streaming.protocol import OutboundFrame, StartedEvent, TerminatedEvent

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
]


async def _spawn_warm(tmp_path: object) -> tuple[asyncio.subprocess.Process, asyncio.StreamReader]:
    read_fd, write_fd = os.pipe()
    env = {key: value for key, value in os.environ.items() if key not in job_env.WRITTEN_BY_APP}
    env.update(
        {
            job_env.NATS_URL: NATS_URL,
            job_env.RUNNER_CONFIG: f"{tmp_path}/missing-url4.toml",
            cp.CONTROL_FD_ENV: str(write_fd),
        }
    )
    # The console script, as the exec wrapper runs it in production.
    proc = await asyncio.create_subprocess_exec(
        str(Path(sys.executable).parent / "screamingface-engine"),
        "run",
        "--warm",
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        pass_fds=(write_fd,),
    )
    os.close(write_fd)
    reader = asyncio.StreamReader()
    await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), os.fdopen(read_fd, "rb", buffering=0)
    )
    return proc, reader


async def _frames(topic: str) -> list[OutboundFrame]:
    consumer = JetStreamConsumer(NATS_URL)
    frames: list[OutboundFrame] = []
    try:
        async for frame in consumer.subscribe(topic):
            frames.append(frame)
            if isinstance(frame, TerminatedEvent):
                return frames
    finally:
        await consumer.close()
    return frames


async def test_warm_child_sends_ready_then_reads_one_spec_then_exits(tmp_path: object) -> None:
    proc, control = await _spawn_warm(tmp_path)
    try:
        ready = cp.decode_ready(await asyncio.wait_for(control.readline(), timeout=60))
        assert ready.pid == proc.pid
        assert ready.world_ok is False  # WC-D3: no world config here

        topic = f"warm-real-{uuid4().hex}"
        spec = {
            job_env.TOPIC: topic,
            job_env.EXPRESSION: "'hi'",
            job_env.JOB_DEADLINE_S: "30",
            # The reclaim keeps only the terminal frame; the grace keeps the whole run readable
            # for this reader, which subscribes BEFORE the spec is sent anyway.
            job_env.STREAM_GRACE_S: "2",
        }
        reading = asyncio.ensure_future(_frames(topic))
        await asyncio.sleep(0.2)
        assert proc.stdin is not None
        proc.stdin.write(cp.encode_spec(spec, io_concurrency=1))
        await proc.stdin.drain()
        proc.stdin.close()
        assert await asyncio.wait_for(control.readline(), timeout=10) == cp.ACK

        frames = await asyncio.wait_for(reading, timeout=30)
        assert isinstance(frames[0], StartedEvent)
        assert isinstance(frames[-1], TerminatedEvent) and frames[-1].data.status == "failed"
        assert await asyncio.wait_for(proc.wait(), timeout=30) == 0
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def test_a_warm_child_whose_worker_goes_away_exits_without_running(
    tmp_path: object,
) -> None:
    """contracts.md C5: stdin closes before a spec → the child exits 0, having run nothing."""
    proc, control = await _spawn_warm(tmp_path)
    try:
        cp.decode_ready(await asyncio.wait_for(control.readline(), timeout=60))
        assert proc.stdin is not None
        proc.stdin.close()
        assert await asyncio.wait_for(proc.wait(), timeout=10) == 0
        assert await control.readline() == b""  # no ACK, no REFUSED
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def test_a_warm_child_refuses_an_unknown_spec_version(tmp_path: object) -> None:
    """WC-D9 on the real entrypoint: REFUSED <code> and exit 2, before any run code."""
    proc, control = await _spawn_warm(tmp_path)
    try:
        cp.decode_ready(await asyncio.wait_for(control.readline(), timeout=60))
        assert proc.stdin is not None
        proc.stdin.write(b'{"spec_version":"3","env":{},"io_concurrency":1}\n')
        await proc.stdin.drain()
        proc.stdin.close()
        answer = await asyncio.wait_for(control.readline(), timeout=10)
        assert cp.refused_code(answer) == "unsupported_spec_version"
        assert await asyncio.wait_for(proc.wait(), timeout=10) == 2
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
