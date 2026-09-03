"""The run queue's stream declaration and publish path (OME-1088).

The queue is a SINGLETON stream (`url4-runq`) with `retention=WorkQueue`, file storage and a
single-node-safe default replica count — the durable substrate OME-1086's worker pool pulls
from. Publishing sets
`Nats-Msg-Id` to the run's topic so the broker deduplicates a retried submission within
`duplicate_window`: the queue's `JobAlreadyExists` equivalent, with no lookup table.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from nats.js.api import RetentionPolicy, StorageType
from nats.js.errors import BadRequestError
from pydantic import ValidationError

from screamingface_engine.config import Settings
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
    """The spec table, pinned: WorkQueue retention, file storage, the default replica count, and
    a name OUTSIDE the per-run `url4-cloud_` prefix (Trap 1 — the sweep deletes anything
    `owns_stream` accepts).

    AIDEV-NOTE: the replica assertion was 3 until 2026-09-03. It is 1 now (owner-approved edit
    to a prior test — see `docs/work/2026-09-03-OME-1088-run-queue-replicas-knob.md`): a
    single-node broker refuses `replicas > 1`, and single-node is what the chart's bundled NATS
    subchart ships. The count is configuration now (`Settings.run_queue_replicas`), pinned end
    to end by `test_run_queue_replicas_setting.py`.
    """
    fake = _FakeJetStream()
    await _queue(fake).ensure_stream()

    added = fake.added[0]
    assert added["name"] == RUN_QUEUE_STREAM
    assert not added["name"].startswith("url4-cloud_")
    assert added["subjects"] == [RUN_QUEUE_SUBJECT]
    assert added["retention"] is RetentionPolicy.WORK_QUEUE
    assert added["storage"] is StorageType.FILE
    assert added["num_replicas"] == 1
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


# --- the BadRequestError the queue must NOT swallow (review follow-up) ----------------------


class _ConflictingStreamJS(_FakeJetStream):
    """A broker whose `add_stream` answers a REAL config conflict — a 400 carrying a
    different JetStream err_code (here: 10052, a generic bad-request), the shape an
    operator-edited or version-skewed stream produces."""

    def __init__(self, err_code: int) -> None:
        super().__init__()
        self._err_code = err_code

    async def add_stream(self, **kwargs: Any) -> object:
        raise BadRequestError(
            code=400,
            err_code=self._err_code,
            description="retention policy mismatch",
        )


async def test_a_config_conflict_under_bad_request_error_is_raised_not_swallowed() -> None:
    """`ensure_stream` tolerates "stream name already in use" (err_code 10058) — but the
    TYPE alone cannot say that: a genuine configuration conflict answers with the same
    `BadRequestError`. Treating every 400 as "already declared" ran the queue on settings
    nobody agreed to, silently. Only 10058 is benign; everything else surfaces."""
    from nats.js.errors import BadRequestError  # noqa: F811 — local to the conflicting shape

    fake = _ConflictingStreamJS(err_code=10_052)
    with pytest.raises(BadRequestError, match="retention policy mismatch"):
        await _queue(fake).ensure_stream()
    assert fake.added == []  # nothing was declared; nothing was marked ensured


async def test_the_name_in_use_error_code_remains_benign() -> None:
    """The one tolerated 400: err_code 10058, "stream name already in use" — declared by
    another replica or an earlier connection. `ensure_stream` returns normally."""
    fake = _ConflictingStreamJS(err_code=10_058)
    await _queue(fake).ensure_stream()


@pytest.mark.asyncio
async def test_publish_stamps_the_enqueue_moment() -> None:
    """The publish-time stamp (review follow-up): JetStream's message metadata records the
    DELIVERY moment, not the enqueue moment — a run that sits backlogged past its deadline
    and is only then pulled reads as age ~0, and the claim-time expiry drop never fires for
    exactly the runs it exists to catch. The publisher stamps the acceptance wall-clock;
    the worker reads it back at claim time."""
    from screamingface_engine.subjects import ENQUEUED_AT_HEADER

    fake = _FakeJetStream()

    await _queue(fake).publish(encode_message(topic="topic-stamped", url4="gpt()", deadline_s=600))

    headers = fake.published[0][2]
    assert ENQUEUED_AT_HEADER in headers
    stamped = datetime.fromisoformat(headers[ENQUEUED_AT_HEADER])
    assert stamped.tzinfo is not None
    assert (datetime.now(UTC) - stamped).total_seconds() < 60


def test_the_fleet_ack_pending_default_is_not_replica_derived() -> None:
    """`max_ack_pending` is a WHOLE-CONSUMER bound shared by every puller in the fleet, not
    a per-worker limit; deriving it from the stream's replica count capped the entire fleet
    at 12 in-flight runs. This pins the decoupling so the conflation is not reintroduced."""
    from screamingface_engine import runner_queue

    assert runner_queue.DEFAULT_MAX_ACK_PENDING != (
        runner_queue.QUEUE_REPLICAS * runner_queue.DEFAULT_WORKER_SLOTS
    )
    assert runner_queue.DEFAULT_MAX_ACK_PENDING >= 64


def test_settings_rejects_a_sweepable_run_queue_stream_name() -> None:
    """V-8: the `url4-cloud_` naming rule was an unenforced comment at the field. The
    orphan sweep deletes any stream `owns_stream()` accepts, and the queue is the one
    stream an accepted run may not be lost from — so a queue named under the per-run
    prefix is a data-loss config, and it must be a STARTUP error, not a latent one
    waiting on every composition root remembering the exclusion."""
    with pytest.raises(ValidationError, match="url4-cloud_"):
        Settings(run_queue_stream="url4-cloud_prod-runq")
    # The default and an ordinary rename stay legal.
    assert Settings().run_queue_stream == RUN_QUEUE_STREAM
    assert Settings(run_queue_stream="prod-runq").run_queue_stream == "prod-runq"
