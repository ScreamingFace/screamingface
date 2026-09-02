"""The run queue's stream declaration and publish path (OME-1088).

The queue is a SINGLETON stream (`url4-runq`) with `retention=WorkQueue`, file storage and 3
replicas — the durable substrate OME-1086's worker pool pulls from. Publishing sets
`Nats-Msg-Id` to the run's topic so the broker deduplicates a retried submission within
`duplicate_window`: the queue's `JobAlreadyExists` equivalent, with no lookup table.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from nats.js.api import RetentionPolicy, StorageType

from screamingface_engine.runner_queue import RunQueue, encode_message
from screamingface_engine.subjects import RUN_QUEUE_STREAM, RUN_QUEUE_SUBJECT

pytestmark = pytest.mark.asyncio


class _RaisingFetchSub:
    """A pull subscription whose `fetch` behaves like the real broker's: it RAISES on an
    empty window instead of returning an empty list (nats-py's `_fetch_one`/
    `FetchTimeoutError`). A fake that returns `[]` masks an uncaught-timeout crash."""

    async def fetch(self, batch: int, timeout: float | None = None) -> list[Any]:
        raise TimeoutError("nats: timeout")

    async def unsubscribe(self) -> None:
        pass


class _FakeJetStream:
    """The slice of `JetStreamContext` the queue uses, recording every call."""

    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []
        self.published: list[tuple[str, bytes, dict[str, str]]] = []
        self.api_calls = 0
        self._state: dict[str, Any] = {"messages": 0, "first_ts": None}
        self._prefix = "$JS.API"
        self.pull_sub: Any = _RaisingFetchSub()

    async def pull_subscribe(self, *args: Any, **kwargs: Any) -> Any:
        return self.pull_sub

    async def add_stream(self, **kwargs: Any) -> object:
        self.added.append(kwargs)
        return object()

    async def publish(
        self, subject: str, payload: bytes = b"", headers: dict[str, str] | None = None, **_: Any
    ) -> object:
        self.published.append((subject, payload, headers or {}))
        return SimpleNamespace(stream=RUN_QUEUE_STREAM, seq=len(self.published))

    async def _api_request(self, subject: str, req: bytes = b"", **_: Any) -> dict[str, Any]:
        self.api_calls += 1
        return {"state": dict(self._state)}


def _queue(fake: _FakeJetStream, **kwargs: Any) -> RunQueue:
    queue = RunQueue("nats://unused:4222", **kwargs)

    async def _fake_jetstream() -> _FakeJetStream:
        return fake

    queue._jetstream = _fake_jetstream  # type: ignore[assignment,method-assign]
    return queue


async def test_the_queue_stream_is_declared_with_the_spec_properties() -> None:
    """The spec table, pinned: WorkQueue retention, file storage, 3 replicas, and a name OUTSIDE
    the per-run `url4-cloud_` prefix (Trap 1 — the sweep deletes anything `owns_stream` accepts)."""
    fake = _FakeJetStream()
    await _queue(fake).ensure_stream()

    added = fake.added[0]
    assert added["name"] == RUN_QUEUE_STREAM
    assert not added["name"].startswith("url4-cloud_")
    assert added["subjects"] == [RUN_QUEUE_SUBJECT]
    assert added["retention"] is RetentionPolicy.WORK_QUEUE
    assert added["storage"] is StorageType.FILE
    assert added["num_replicas"] == 3
    # The dedupe window is what makes a retried submission a no-op rather than a second run.
    assert added["duplicate_window"] == 120.0
    # max_age is a storage backstop only — never a correctness mechanism.
    assert added["max_age"] == 86_400.0


async def test_duplicate_publish_carries_the_same_dedupe_key() -> None:
    """A retried submission of one topic must reach the broker with the SAME `Nats-Msg-Id`, so
    the broker's dedupe window collapses it into the original message — exactly one run."""
    fake = _FakeJetStream()
    queue = _queue(fake)
    message = encode_message("topic-a", "'hi'!'go'", 60)

    await queue.publish(message)
    await queue.publish(message)

    assert [headers["Nats-Msg-Id"] for _, _, headers in fake.published] == ["topic-a", "topic-a"]
    assert [subject for subject, _, _ in fake.published] == [RUN_QUEUE_SUBJECT] * 2


async def test_publish_awaits_the_broker_acknowledgement() -> None:
    """The caller must know the run was durably accepted before it tells the client so — an
    accepted run may not be lost."""
    fake = _FakeJetStream()
    await _queue(fake).publish(encode_message("topic-a", "'hi'", 60))
    assert len(fake.published) == 1


async def test_depth_and_oldest_age_come_from_one_stream_info_round_trip() -> None:
    fake = _FakeJetStream()
    first_ts = (datetime.now(UTC) - timedelta(seconds=42)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    fake._state = {"messages": 3, "first_ts": first_ts}
    queue = _queue(fake)

    assert await queue.depth() == 3
    age = await queue.oldest_age()
    assert age is not None and age == pytest.approx(42, abs=5)
    assert fake.api_calls == 1


async def test_depth_is_cached_within_the_ttl() -> None:
    fake = _FakeJetStream()
    fake._state = {"messages": 1, "first_ts": None}
    queue = _queue(fake)

    assert await queue.depth() == 1
    assert await queue.depth() == 1
    assert fake.api_calls == 1, "the second read must come from the cache"


async def test_the_cache_expires_after_the_ttl() -> None:
    fake = _FakeJetStream()
    fake._state = {"messages": 1, "first_ts": None}
    queue = _queue(fake, state_cache_ttl_s=0.0)

    assert await queue.depth() == 1
    fake._state["messages"] = 5  # the broker changed underneath
    assert await queue.depth() == 5
    assert fake.api_calls == 2


async def test_an_idle_poll_returns_no_messages_rather_than_raising() -> None:
    """The real broker RAISES from `fetch` when nothing arrives — nats-py never returns an
    empty list. A `pull` that propagates that kills the worker's claim loop on its first
    poll of an idle queue, so the timeout must read as "nothing to claim"."""
    fake = _FakeJetStream()
    assert fake.pull_sub.__class__ is _RaisingFetchSub  # the honest fake, not a [] one

    assert await _queue(fake).pull(batch=1, timeout_s=0.01) == []


async def test_an_empty_queue_reports_no_age_even_though_the_server_sends_a_zero_time() -> None:
    """The server answers an empty stream with the Go zero time, not a null —
    `"0001-01-01T00:00:00Z"` is the real wire shape and must read as "no queued run";
    taking it literally reports a ~6.4e10-second age and the idle-queue alert fires
    forever."""
    fake = _FakeJetStream()
    fake._state = {"messages": 0, "first_ts": "0001-01-01T00:00:00Z"}
    assert await _queue(fake).oldest_age() is None

    # Belt-and-braces: a response that disagrees with itself (messages > 0, zero time)
    # must also read as "no age", never as a negative-or-ancient timestamp.
    disagreeing = _FakeJetStream()
    disagreeing._state = {"messages": 2, "first_ts": "0001-01-01T00:00:00Z"}
    assert await _queue(disagreeing, state_cache_ttl_s=0.0).oldest_age() is None
