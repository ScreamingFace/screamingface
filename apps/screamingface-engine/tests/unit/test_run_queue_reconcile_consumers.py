"""`RunQueue.reconcile_consumers()` brings each live bucket consumer's `max_ack_pending` to the
configured value, in place (OME-1314, spec 2026-11-10-per-user-parallel-runs D2/F1).

FEATURE: a runner rollout with a new `runnerPool.maxAckPending` takes effect on the existing
queue consumers, not only on consumers created after the change.

WHY the reconcile is tested against a fake: its contract is the calls it makes (which consumer,
which config, what it skips) and what it does on each broker failure (log and continue, never
raise). The real broker's in-place edit is pinned by the integration file, not here.

WHY a recording logger instead of caplog: the app logger sets propagate=False after create_app,
so caplog is unreliable for `runner_queue`'s records.

This file keeps its own fake JetStream: the reconcile needs `add_consumer`, which no
existing fake records.
"""

import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest
from nats.js.api import AckPolicy, ConsumerConfig, ConsumerInfo
from nats.js.errors import NotFoundError, ServiceUnavailableError

from screamingface_engine import runner_queue
from screamingface_engine.runner_queue import RunQueue, _consumer_for

pytestmark = pytest.mark.asyncio

STREAM = "url4-runq-test"
PREFIX = "url4-runq-test"


def _config(subject: str, max_ack_pending: int) -> ConsumerConfig:
    return ConsumerConfig(
        durable_name=_consumer_for(subject),
        filter_subject=subject,
        ack_policy=AckPolicy.EXPLICIT,
        ack_wait=60.0,
        max_deliver=5,
        max_ack_pending=max_ack_pending,
    )


def _name(config: ConsumerConfig) -> str:
    """The durable name `_config` always sets; narrows nats' `str | None` for typed keys."""
    assert config.durable_name is not None
    return config.durable_name


def _info(config: ConsumerConfig) -> ConsumerInfo:
    return ConsumerInfo(
        name=_name(config),
        stream_name=STREAM,
        config=config,
        created=datetime.now(UTC),
        num_ack_pending=4,
        num_pending=2,
    )


class _FakeJetStream:
    """The slice of `JetStreamContext` the reconcile uses.

    `consumers` maps consumer name -> `ConsumerInfo` or an exception to raise (absent = not
    found). `added` records every config sent through `add_consumer`.
    """

    def __init__(
        self,
        consumers: dict[str, ConsumerInfo | BaseException],
        add_error: BaseException | None = None,
    ) -> None:
        self.consumers = consumers
        self.add_error = add_error
        self.added: list[tuple[str, ConsumerConfig]] = []

    async def consumer_info(self, stream: str, consumer: str, timeout: Any = None) -> Any:
        found = self.consumers.get(consumer)
        if found is None:
            raise NotFoundError(code=404, err_code=10014, description="consumer not found")
        if isinstance(found, BaseException):
            raise found
        return found

    async def add_consumer(
        self, stream: str, config: Any = None, timeout: Any = None, **params: Any
    ) -> Any:
        if self.add_error is not None:
            raise self.add_error
        self.added.append((stream, config))
        return _info(config)


class _RecordingLogger:
    """Records (level, message) for the reconcile's info and warning lines."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def info(self, msg: str, *args: Any) -> None:
        self.records.append(("info", msg % args))

    def warning(self, msg: str, *args: Any) -> None:
        self.records.append(("warning", msg % args))


def _queue(fake: _FakeJetStream, *, bucket_count: int = 3, max_ack_pending: int = 24) -> RunQueue:
    queue = RunQueue(
        "nats://unused:4222",
        stream=STREAM,
        subject_prefix=PREFIX,
        bucket_count=bucket_count,
        max_ack_pending=max_ack_pending,
    )

    async def _fake_jetstream() -> _FakeJetStream:
        return fake

    queue._jetstream = _fake_jetstream  # type: ignore[assignment,method-assign]
    return queue


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _RecordingLogger:
    rec = _RecordingLogger()
    monkeypatch.setattr(runner_queue, "logger", rec)
    return rec


subjects = [f"{PREFIX}.{i:02x}" for i in range(3)]


async def test_a_lower_value_is_raised_in_place(recorder: _RecordingLogger) -> None:
    original = _config(subjects[0], max_ack_pending=4)
    fake = _FakeJetStream({_name(original): _info(original)})

    updated = await _queue(fake, bucket_count=1, max_ack_pending=24).reconcile_consumers()

    assert updated == 1
    assert fake.added == [(STREAM, dataclasses.replace(original, max_ack_pending=24))]
    info_lines = [msg for level, msg in recorder.records if level == "info"]
    assert len(info_lines) == 1
    assert "4 -> 24" in info_lines[0]
    assert _name(original) in info_lines[0]


async def test_a_higher_value_is_lowered_in_place(recorder: _RecordingLogger) -> None:
    original = _config(subjects[0], max_ack_pending=24)
    fake = _FakeJetStream({_name(original): _info(original)})

    updated = await _queue(fake, bucket_count=1, max_ack_pending=4).reconcile_consumers()

    assert updated == 1
    assert len(fake.added) == 1
    assert fake.added[0][1].max_ack_pending == 4


async def test_an_equal_value_is_not_written(recorder: _RecordingLogger) -> None:
    original = _config(subjects[0], max_ack_pending=24)
    fake = _FakeJetStream({_name(original): _info(original)})

    updated = await _queue(fake, bucket_count=1, max_ack_pending=24).reconcile_consumers()

    assert updated == 0
    assert fake.added == []


async def test_a_missing_consumer_is_skipped(recorder: _RecordingLogger) -> None:
    first = _config(subjects[0], max_ack_pending=4)
    third = _config(subjects[2], max_ack_pending=4)
    fake = _FakeJetStream({_name(first): _info(first), _name(third): _info(third)})

    updated = await _queue(fake, bucket_count=3, max_ack_pending=24).reconcile_consumers()

    assert updated == 2
    assert [config.durable_name for _, config in fake.added] == [
        first.durable_name,
        third.durable_name,
    ]


async def test_only_max_ack_pending_changes(recorder: _RecordingLogger) -> None:
    original = dataclasses.replace(
        _config(subjects[0], max_ack_pending=4),
        description="keep",
        max_waiting=512,
        num_replicas=1,
    )
    fake = _FakeJetStream({_name(original): _info(original)})

    await _queue(fake, bucket_count=1, max_ack_pending=24).reconcile_consumers()

    ((_, sent),) = fake.added
    assert sent == dataclasses.replace(original, max_ack_pending=24)
    assert sent.ack_wait == 60.0
    assert sent.max_deliver == 5
    assert sent.filter_subject == subjects[0]
    assert sent.durable_name == original.durable_name


async def test_a_broker_error_on_one_bucket_is_logged_and_the_rest_continue(
    recorder: _RecordingLogger,
) -> None:
    broken = _config(subjects[0], max_ack_pending=4)
    healthy_1 = _config(subjects[1], max_ack_pending=4)
    healthy_2 = _config(subjects[2], max_ack_pending=4)
    fake = _FakeJetStream(
        {
            _name(broken): ServiceUnavailableError(),
            _name(healthy_1): _info(healthy_1),
            _name(healthy_2): _info(healthy_2),
        }
    )

    updated = await _queue(fake, max_ack_pending=24).reconcile_consumers()

    assert updated == 2
    warnings = [msg for level, msg in recorder.records if level == "warning"]
    assert len(warnings) == 1
    assert _name(broken) in warnings[0]
    assert "ServiceUnavailableError" in warnings[0]


async def test_a_failed_update_is_logged_and_not_counted(recorder: _RecordingLogger) -> None:
    original = _config(subjects[0], max_ack_pending=4)
    fake = _FakeJetStream({_name(original): _info(original)}, add_error=RuntimeError("boom"))

    updated = await _queue(fake, bucket_count=1, max_ack_pending=24).reconcile_consumers()

    assert updated == 0
    warnings = [msg for level, msg in recorder.records if level == "warning"]
    assert len(warnings) == 1
    assert "RuntimeError" in warnings[0]


async def test_an_unreachable_broker_returns_zero(recorder: _RecordingLogger) -> None:
    queue = RunQueue(
        "nats://unused:4222",
        stream=STREAM,
        subject_prefix=PREFIX,
        bucket_count=3,
        max_ack_pending=24,
    )

    async def _down() -> Any:
        raise OSError("down")

    queue._jetstream = _down  # type: ignore[assignment,method-assign]

    updated = await queue.reconcile_consumers()

    assert updated == 0
    warnings = [msg for level, msg in recorder.records if level == "warning"]
    assert len(warnings) == 1
    assert "OSError" in warnings[0]


class _BindingJetStream(_FakeJetStream):
    """Adds `pull_subscribe`, so the worker's subscription bind runs against the fake."""

    def __init__(self, consumers: dict[str, ConsumerInfo | BaseException]) -> None:
        super().__init__(consumers)
        self.binds = 0
        self.infos = 0

    async def consumer_info(self, stream: str, consumer: str, timeout: Any = None) -> Any:
        self.infos += 1
        return await super().consumer_info(stream, consumer, timeout)

    async def pull_subscribe(self, *args: Any, **kwargs: Any) -> object:
        self.binds += 1
        return object()


async def test_the_ttl_rebind_never_writes_the_consumer(
    recorder: _RecordingLogger, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT (spec D2): only a starting worker writes `max_ack_pending`. The 300 s re-bind
    of a held subscription must not, or an old pod draining with the old value would write it
    back during a rollout."""
    original = _config(subjects[0], max_ack_pending=4)
    fake = _BindingJetStream({_name(original): _info(original)})
    queue = _queue(fake, bucket_count=1, max_ack_pending=24)
    clock = [1000.0]
    monkeypatch.setattr(runner_queue.time, "monotonic", lambda: clock[0])

    await queue._bound_subscription(fake, subjects[0])
    clock[0] += runner_queue.PULL_SUB_TTL_S + 1
    await queue._bound_subscription(fake, subjects[0])

    assert fake.binds == 2  # the TTL expired, so the subscription was bound again
    assert fake.added == []
    assert fake.infos == 0
