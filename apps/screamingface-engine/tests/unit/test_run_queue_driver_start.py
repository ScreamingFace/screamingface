"""E5 P2 spec §4.4, R3 and R15: a driver-started run's queue message.

FEATURE: a detached Run (OME-1837). The driver sets a result prefix and `exclusive` on every start
it sends, and nothing else sets either, so "driver-started", "exclusive", "has a result prefix"
and "version 3" name the same runs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.runner_queue import decode_message, encode_message

PREFIX = "runs/01JD5Z8Q0000000000000000/3"


def test_a_driver_start_is_a_version_3_message_with_its_prefix_and_flag() -> None:
    env = decode_message(
        encode_message("t1", "openai/gpt-5", 60, result_prefix=PREFIX, exclusive=True)
    )

    assert env[job_env.RESULT_PREFIX] == PREFIX
    assert env[job_env.EXCLUSIVE] == "1"
    assert env[job_env.SPEC_VERSION] == "3"


def test_a_start_without_them_is_todays_message_byte_for_byte() -> None:
    """INVARIANT (plan E2): the new fields are written only when set."""
    today = encode_message("t1", "openai/gpt-5", 60)

    assert encode_message("t1", "openai/gpt-5", 60, result_prefix=None, exclusive=False) == today
    env = decode_message(today)
    assert job_env.RESULT_PREFIX not in env
    assert job_env.EXCLUSIVE not in env
    assert env[job_env.SPEC_VERSION] == job_env.CURRENT_SPEC_VERSION == "2"


def test_a_worker_of_this_version_reads_version_3() -> None:
    assert job_env.SUPPORTED_SPEC_MAJORS == {"1", "2", "3"}


def test_the_runner_reads_the_prefix_and_flag_back() -> None:
    env = decode_message(
        encode_message("t1", "openai/gpt-5", 60, result_prefix=PREFIX, exclusive=True)
    )

    assert job_env.result_prefix_from_env(env) == PREFIX
    assert job_env.exclusive_from_env(env)
    assert job_env.result_prefix_from_env({}) is None
    assert not job_env.exclusive_from_env({})


class _Queue:
    def __init__(self) -> None:
        self.published: list[bytes] = []

    async def publish(
        self, message: bytes, *, identity: Any = None, enqueued_at: Any = None
    ) -> None:
        self.published.append(message)

    async def depth(self) -> int:
        return 0

    async def oldest_age(self) -> float | None:
        return None


class _Publisher:
    async def last_frame(self, topic: str) -> Any:
        return None

    async def stream_exists(self, topic: str) -> bool:
        return True

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: Any) -> None:
        return None

    async def flush(self) -> None:
        return None


class _Control:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


@pytest.mark.asyncio
async def test_the_queue_runner_carries_the_driver_fields_into_its_message() -> None:
    queue = _Queue()
    runner = QueueJobRunner(
        queue=queue,
        publisher=_Publisher(),
        control=_Control(),
        clock=lambda: datetime(2026, 11, 12, tzinfo=UTC),
        capability_lifetime_s=60,
        depth_ceiling=10,
        caller_inflight_cap=8,
    )

    await runner.schedule("t1", "openai/gpt-5", 60, result_prefix=PREFIX, exclusive=True)
    await runner.schedule("t2", "openai/gpt-5", 60)

    first, second = (decode_message(message) for message in queue.published)
    assert (first[job_env.RESULT_PREFIX], first[job_env.EXCLUSIVE]) == (PREFIX, "1")
    assert job_env.RESULT_PREFIX not in second
    assert job_env.EXCLUSIVE not in second


class _Tail(_Publisher):
    def __init__(self, frame: Any) -> None:
        self.frame = frame

    async def last_frame(self, topic: str) -> Any:
        if isinstance(self.frame, Exception):
            raise self.frame
        return self.frame


@pytest.mark.asyncio
async def test_a_stop_lands_only_once_the_stream_ends_in_a_terminal_frame() -> None:
    """#1759 review: a stop a worker took is not done until its stopped frame is durable."""
    from screamingface_engine.ports import QueueReadError
    from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

    def runner(frame: Any) -> QueueJobRunner:
        return QueueJobRunner(
            queue=_Queue(),
            publisher=_Tail(frame),
            control=_Control(),
            clock=lambda: datetime(2026, 11, 12, tzinfo=UTC),
            capability_lifetime_s=60,
            depth_ceiling=10,
            caller_inflight_cap=8,
        )

    stopped = TerminatedEvent(
        id="e1", source=source_for("t1"), subject="t1", data=TerminatedData(status="stopped")
    )

    assert await runner(stopped).stop_landed("t1")
    assert not await runner(None).stop_landed("t1")
    with pytest.raises(QueueReadError):
        await runner(QueueReadError("down")).stop_landed("t1")
