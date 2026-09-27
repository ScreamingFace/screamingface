"""Shared events stream (uniform executor, PRD 01) against a real JetStream.

Every run's frames live on subject `url4-cloud.<topic>` of ONE stream. The frame sequence the
client sees is the PRODUCER sequence, gap-free per topic (erd.md §5, I-EV1..I-EV4).
"""

import asyncio
import contextlib
import os
import socket
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

import nats
import pytest

from screamingface_engine.adapters.jetstream import JetStreamConsumer, JetStreamPublisher
from screamingface_engine.testing.mock_runner import publish_mock_run
from url4.streaming.protocol import (
    LogData,
    LogEvent,
    OutboundFrame,
    OutboundFrameAdapter,
    TerminatedData,
    TerminatedEvent,
)
from url4.streaming.protocol.envelope import source_for

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
    pytest.mark.skipif(
        not _nats_reachable(),
        reason=f"needs a reachable NATS at {NATS_URL} (set URL4_CLOUD_TEST_NATS_URL)",
    ),
]

EXPR = "(gpt,claude)!'hi'"
MOCK_FRAME_COUNT = 11


def _topic(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


async def _take(
    consumer: JetStreamConsumer, topic: str, n: int, **kw: object
) -> list[OutboundFrame]:
    frames: list[OutboundFrame] = []

    async def _read() -> None:
        stream: AsyncIterator[OutboundFrame] = consumer.subscribe(topic, **kw)  # type: ignore[arg-type]
        async for frame in stream:
            frames.append(frame)
            if len(frames) == n:
                return

    await asyncio.wait_for(_read(), timeout=10.0)
    return frames


def _log(topic: str, n: int) -> LogEvent:
    """A SEQUENCED frame, as the url4 producer in the child stamps it."""
    return LogEvent(
        id=uuid4().hex,
        source=source_for(topic),
        subject=topic,
        time=datetime.now(UTC),
        sequence=str(n),
        sequencetype="Integer",
        data=LogData.at("INFO", f"frame {n}"),
    )


def _seqs(frames: list[OutboundFrame]) -> list[int]:
    return [int(f.sequence or 0) for f in frames]


async def test_frame_sequence_on_wire_equals_producer_sequence_for_fresh_run() -> None:
    """EVT-C1 (CHAR): for a run with one writer on a fresh topic, the sequence a subscriber
    sees is 1..n, the same numbers the url4 producer stamped."""
    topic = _topic("evt-c1")
    publisher = JetStreamPublisher(NATS_URL)
    consumer = JetStreamConsumer(NATS_URL)
    try:
        await publish_mock_run(publisher, topic, EXPR)
        await publisher.flush()
        frames = await _take(consumer, topic, MOCK_FRAME_COUNT)
        assert _seqs(frames) == list(range(1, MOCK_FRAME_COUNT + 1))
        assert isinstance(frames[-1], TerminatedEvent)
    finally:
        await publisher.close()
        await consumer.close()


# --- delta: one shared stream -----------------------------------------------------------------

from nats.js.api import StorageType  # noqa: E402
from nats.js.errors import APIError, NotFoundError  # noqa: E402

from screamingface_engine.adapters.jetstream import (  # noqa: E402
    EventsStreamConfig,
    EventsStreamConfigError,
    ensure_events_stream,
    events_store_usage,
    purge_legacy_streams,
)
from screamingface_engine.runner.main import run_and_reclaim  # noqa: E402
from screamingface_engine.subjects import EVENTS_STREAM, subject_for  # noqa: E402


def _terminal(topic: str, status: str = "stopped") -> TerminatedEvent:
    """An UNSEQUENCED terminal frame, as the supervisor, the App tombstone and the
    max-deliveries advisor build them."""
    return TerminatedEvent(
        id=uuid4().hex,
        source=source_for(topic),
        subject=topic,
        time=datetime.now(UTC),
        data=TerminatedData(status=status),  # type: ignore[arg-type]
    )


async def _subject_state(topic: str) -> list[tuple[int, int]]:
    """(stream sequence, producer sequence) of every frame retained on the topic's subject."""
    nc = await nats.connect(NATS_URL)
    try:
        js = nc.jetstream()
        sub = await js.subscribe(subject_for(topic), stream=EVENTS_STREAM, ordered_consumer=True)
        out: list[tuple[int, int]] = []
        info = await js.stream_info(EVENTS_STREAM, subjects_filter=subject_for(topic))
        expected = (info.state.subjects or {}).get(subject_for(topic), 0)
        while len(out) < expected:
            msg = await sub.next_msg(timeout=5.0)
            frame = OutboundFrameAdapter.validate_json(msg.data)
            out.append((msg.metadata.sequence.stream, int(frame.sequence or 0)))
        await sub.unsubscribe()
        return out
    finally:
        await nc.close()


async def _stream_names() -> set[str]:
    nc = await nats.connect(NATS_URL)
    try:
        return {s.config.name for s in await nc.jetstream().streams_info() if s.config.name}
    finally:
        await nc.close()


async def _mock_run(topic: str) -> None:
    publisher = JetStreamPublisher(NATS_URL)
    try:
        await publish_mock_run(publisher, topic, EXPR)
        await publisher.flush()
    finally:
        await publisher.close()


async def test_run_frames_land_in_url4_events_and_no_per_topic_stream_exists() -> None:
    """EVT-8 / EV-H1."""
    topic = _topic("evt-8")
    await _mock_run(topic)
    state = await _subject_state(topic)
    assert [p for _, p in state] == list(range(1, MOCK_FRAME_COUNT + 1))
    assert f"url4-cloud_{topic}" not in await _stream_names()


async def test_fifty_interleaved_runs_each_read_gap_free() -> None:
    """EVT-3 / EV-H3 — and EVT-1: in a shared stream the stream sequence has gaps inside one
    run, so a subscriber that saw the stream sequence would see gaps. It must see 1..n."""
    topics = [_topic("evt-3") for _ in range(50)]
    await asyncio.gather(*(_mock_run(t) for t in topics))
    consumer = JetStreamConsumer(NATS_URL)
    try:
        for topic in topics:
            frames = await _take(consumer, topic, MOCK_FRAME_COUNT)
            assert {f.subject for f in frames} == {topic}
            assert _seqs(frames) == list(range(1, MOCK_FRAME_COUNT + 1))
    finally:
        await consumer.close()


async def test_resume_from_sequence_delivers_the_tail_exactly_once() -> None:
    """EVT-2 / EV-D1, with the mock run's 11 frames standing in for 40: resume at 6 → 6..11."""
    topic = _topic("evt-2")
    other = _topic("evt-2-noise")
    await asyncio.gather(_mock_run(topic), _mock_run(other))
    consumer = JetStreamConsumer(NATS_URL)
    try:
        frames = await _take(consumer, topic, MOCK_FRAME_COUNT - 5, from_sequence=6)
        assert _seqs(frames) == list(range(6, MOCK_FRAME_COUNT + 1))
    finally:
        await consumer.close()


async def test_supervisor_terminal_frame_takes_last_plus_one() -> None:
    """EVT-4 / EV-D2: an unsequenced terminal frame after a child's partial run is
    appended as last + 1."""
    topic = _topic("evt-4")
    child = JetStreamPublisher(NATS_URL)
    supervisor = JetStreamPublisher(NATS_URL)
    try:
        frames = [_log(topic, n) for n in range(1, 8)]
        for frame in frames:
            await child.publish(topic, frame)
        await child.flush()
        assert await supervisor.publish_next(topic, _terminal(topic, "failed"), writer="supervisor")
        assert [p for _, p in await _subject_state(topic)] == list(range(1, 9))
    finally:
        await child.close()
        await supervisor.close()


async def test_tombstone_on_empty_subject_is_sequence_1() -> None:
    """EVT-6 / EV-D4."""
    topic = _topic("evt-6")
    app = JetStreamPublisher(NATS_URL)
    try:
        assert await app.publish_next(topic, _terminal(topic))
        assert [p for _, p in await _subject_state(topic)] == [1]
    finally:
        await app.close()


async def test_publish_next_writes_nothing_after_a_terminal_frame() -> None:
    """I-EV4: one terminal frame per topic, and it is the last."""
    topic = _topic("evt-4b")
    app = JetStreamPublisher(NATS_URL)
    try:
        assert await app.publish_next(topic, _terminal(topic), writer="app")
        assert not await app.publish_next(topic, _terminal(topic), writer="supervisor")
        assert [p for _, p in await _subject_state(topic)] == [1]
    finally:
        await app.close()


async def test_supervisor_retries_on_expected_sequence_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EVT-5 / EV-D3: the writer read a stale tail (a late child frame landed after the read);
    the conditional publish fails, the writer re-reads, and it appends at the new last + 1."""
    topic = _topic("evt-5")
    child = JetStreamPublisher(NATS_URL)
    supervisor = JetStreamPublisher(NATS_URL)
    try:
        for n in range(1, 8):
            await child.publish(topic, _log(topic, n))
        await child.flush()
        real_tail = supervisor._tail  # noqa: SLF001 - the seam under test

        async def stale_then_real(t: str):  # type: ignore[no-untyped-def]
            stale = await real_tail(t)
            monkeypatch.setattr(supervisor, "_tail", real_tail)
            await child.publish(topic, _log(topic, 8))  # the late child frame
            await child.flush()
            return stale

        monkeypatch.setattr(supervisor, "_tail", stale_then_real)
        assert await supervisor.publish_next(topic, _terminal(topic, "failed"), writer="supervisor")
        assert [p for _, p in await _subject_state(topic)] == list(range(1, 10))
        assert supervisor.publish_conflicts == {"supervisor": 1}
    finally:
        await child.close()
        await supervisor.close()


async def test_conflict_with_a_terminal_late_frame_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EVT-5 / EV-D3 second half: if the late frame is itself terminal, write nothing."""
    topic = _topic("evt-5b")
    child = JetStreamPublisher(NATS_URL)
    supervisor = JetStreamPublisher(NATS_URL)
    try:
        await child.publish(topic, _log(topic, 1))
        await child.flush()
        real_tail = supervisor._tail  # noqa: SLF001

        async def stale_then_real(t: str):  # type: ignore[no-untyped-def]
            stale = await real_tail(t)
            monkeypatch.setattr(supervisor, "_tail", real_tail)
            late = _terminal(topic, "succeeded").model_copy(update={"sequence": "2"})
            await child.publish(topic, late)
            await child.flush()
            return stale

        monkeypatch.setattr(supervisor, "_tail", stale_then_real)
        refused = await supervisor.publish_next(
            topic, _terminal(topic, "failed"), writer="supervisor"
        )
        assert not refused
        assert [p for _, p in await _subject_state(topic)] == [1, 2]
    finally:
        await child.close()
        await supervisor.close()


async def test_publish_retry_with_same_msg_id_stores_frame_once() -> None:
    """EVT-7 / EV-D5: `Nats-Msg-Id = <topic>:<seq>`, so a retried frame is deduped."""
    topic = _topic("evt-7")
    publisher = JetStreamPublisher(NATS_URL)
    try:
        for n in (1, 2, 3, 4, 5, 5):
            await publisher.publish(topic, _log(topic, n))
        await publisher.flush()
        assert [p for _, p in await _subject_state(topic)] == [1, 2, 3, 4, 5]
    finally:
        await publisher.close()


async def test_redelivered_run_continues_the_subject_sequence() -> None:
    """Redelivery (K7, MC-D12): a second child runs the topic again from producer sequence 1.
    Its frames must continue the subject gap-free (k+1..), not collide with frames 1..k."""
    topic = _topic("evt-redeliver")
    first = JetStreamPublisher(NATS_URL)
    try:
        for n in range(1, 4):
            await first.publish(topic, _log(topic, n))
        await first.flush()
    finally:
        await first.close()
    await _mock_run(topic)
    assert [p for _, p in await _subject_state(topic)] == list(range(1, 4 + MOCK_FRAME_COUNT))


async def test_teardown_reclaims_subject_but_keeps_the_terminal_frame() -> None:
    """EVT-9 / EV-H4. DEVIATION from the PRD ("no frame"): the purge keeps the last frame
    (`keep=1`). The terminal frame is the evidence the App admission and the worker dedupe gate
    read to know a run is over; a shared stream has no per-run stream whose absence could carry
    that evidence. `max_age` removes it after 24 h."""
    topic = _topic("evt-9")
    publisher = JetStreamPublisher(NATS_URL)
    try:

        async def run_once() -> None:
            await publish_mock_run(publisher, topic, EXPR)
            await publisher.flush()

        await run_and_reclaim(publisher, topic, run_once, grace_s=0.0)
        assert [p for _, p in await _subject_state(topic)] == [MOCK_FRAME_COUNT]
        assert isinstance(await publisher.last_frame(topic), TerminatedEvent)
    finally:
        await publisher.close()


async def test_delete_run_reclaims_only_its_subject() -> None:
    """EVT-10 / EV-D11."""
    a, b = _topic("evt-10a"), _topic("evt-10b")
    await asyncio.gather(_mock_run(a), _mock_run(b))
    consumer = JetStreamConsumer(NATS_URL)
    try:
        await consumer.delete_stream(a)
        assert [p for _, p in await _subject_state(a)] == [MOCK_FRAME_COUNT]
        assert [p for _, p in await _subject_state(b)] == list(range(1, MOCK_FRAME_COUNT + 1))
    finally:
        await consumer.close()


async def test_resume_below_the_retained_frames_reports_reclaimed() -> None:
    """A resume cursor that points at frames the reclaim removed cannot be served: the
    consumer raises `StreamNotFoundError`, which the bridge turns into `stream_reclaimed`."""
    from url4.streaming.interfaces import StreamNotFoundError

    topic = _topic("evt-reclaimed")
    await _mock_run(topic)
    consumer = JetStreamConsumer(NATS_URL)
    try:
        await consumer.delete_stream(topic)
        with pytest.raises(StreamNotFoundError):
            await _take(consumer, topic, 1, from_sequence=3)
    finally:
        await consumer.close()


# --- stream configuration (isolated streams, so the shared one is never touched) ----------


def _isolated(**overrides: object) -> EventsStreamConfig:
    tag = uuid4().hex[:12]
    return EventsStreamConfig(name=f"evt-test-{tag}", subjects=(f"evt-test-{tag}.*",), **overrides)  # type: ignore[arg-type]


async def _js():  # type: ignore[no-untyped-def]
    nc = await nats.connect(NATS_URL)
    return nc, nc.jetstream()


async def test_per_subject_cap_drops_oldest_of_that_run_only() -> None:
    """EVT-11 / EV-D6."""
    cfg = _isolated(max_msgs_per_subject=100, max_bytes=64 * 1024 * 1024)
    nc, js = await _js()
    try:
        await ensure_events_stream(js, cfg, update=True)
        prefix = cfg.subjects[0].removesuffix("*")
        for n in range(150):
            await js.publish(f"{prefix}a", str(n).encode())
        for n in range(10):
            await js.publish(f"{prefix}b", str(n).encode())
        info = await js.stream_info(cfg.name, subjects_filter=">")
        assert info.state.subjects == {f"{prefix}a": 100, f"{prefix}b": 10}
        first_a = await js.get_msg(cfg.name, subject=f"{prefix}a", seq=1, next=True)
        assert first_a.data == b"50"
    finally:
        await js.delete_stream(cfg.name)
        await nc.close()


async def test_full_store_drops_oldest_and_gauge_reports_ratio() -> None:
    """EVT-12 / EV-E1."""
    cfg = _isolated(max_bytes=64 * 1024, max_msg_size=8 * 1024)
    nc, js = await _js()
    try:
        await ensure_events_stream(js, cfg, update=True)
        subject = cfg.subjects[0].replace("*", "x")
        for _ in range(40):
            await js.publish(subject, b"x" * 4000)
        used, ratio = await events_store_usage(js, cfg)
        assert used <= cfg.max_bytes
        assert ratio >= 0.9
        info = await js.stream_info(cfg.name)
        assert info.state.first_seq > 1  # the oldest frames were dropped
    finally:
        await js.delete_stream(cfg.name)
        await nc.close()


async def test_startup_updates_mutable_stream_config() -> None:
    """EVT-13 / EV-D7."""
    cfg = _isolated(max_bytes=1024 * 1024)
    nc, js = await _js()
    try:
        await ensure_events_stream(js, cfg, update=True)
        bigger = EventsStreamConfig(**{**cfg.__dict__, "max_bytes": 2 * 1024 * 1024})
        await ensure_events_stream(js, bigger, update=True)
        assert (await js.stream_info(cfg.name)).config.max_bytes == 2 * 1024 * 1024
    finally:
        await js.delete_stream(cfg.name)
        await nc.close()


async def test_lazy_ensure_never_updates_an_existing_stream() -> None:
    """A child (lazy ensure, `update=False`) must not rewrite the operator's stream config."""
    cfg = _isolated(max_bytes=2 * 1024 * 1024)
    nc, js = await _js()
    try:
        await ensure_events_stream(js, cfg, update=True)
        smaller = EventsStreamConfig(**{**cfg.__dict__, "max_bytes": 1024 * 1024})
        await ensure_events_stream(js, smaller, update=False)
        assert (await js.stream_info(cfg.name)).config.max_bytes == 2 * 1024 * 1024
    finally:
        await js.delete_stream(cfg.name)
        await nc.close()


async def test_startup_fails_on_immutable_mismatch_naming_field() -> None:
    """EVT-14 / EV-D8."""
    cfg = _isolated(storage=StorageType.MEMORY, max_bytes=1024 * 1024)
    nc, js = await _js()
    try:
        await ensure_events_stream(js, cfg, update=True)
        as_file = EventsStreamConfig(**{**cfg.__dict__, "storage": StorageType.FILE})
        with pytest.raises(EventsStreamConfigError, match="storage"):
            await ensure_events_stream(js, as_file, update=True)
    finally:
        await js.delete_stream(cfg.name)
        await nc.close()


async def test_startup_fails_when_max_bytes_exceeds_store() -> None:
    """EVT-15 / EV-D9."""
    cfg = _isolated(max_bytes=1 << 60)
    nc, js = await _js()
    try:
        with pytest.raises(EventsStreamConfigError, match="events.maxBytes"):
            await ensure_events_stream(js, cfg, update=True)
    finally:
        await nc.close()


async def test_startup_fails_while_a_legacy_stream_overlaps_naming_the_purge_command() -> None:
    """Rollout order (erd.md §10, corrected): a legacy stream captures `url4-cloud.<topic>`, which
    overlaps `url4-cloud.*`, so the events stream cannot be created until the purge ran. Since
    the owner's 2026-09-27 rollout decision the App and worker (`update=True`) purge it
    themselves; the lazy path (`update=False`) still refuses, naming the command."""
    cfg = _isolated()
    prefix = cfg.subjects[0].removesuffix("*")
    legacy = f"url4-cloud_{uuid4().hex}"
    nc, js = await _js()
    try:
        await js.add_stream(name=legacy, subjects=[f"{prefix}sometopic"])
        with pytest.raises(EventsStreamConfigError, match="purge-legacy-streams"):
            await ensure_events_stream(js, cfg, update=False)
    finally:
        await js.delete_stream(legacy)
        await nc.close()


async def test_startup_deletes_an_overlapping_legacy_stream_and_declares_the_shared_one() -> None:
    """The App and worker's own migration, on a real broker: the legacy stream is gone, the
    shared stream exists, and a legacy stream can no longer be created over it (the old App
    still up during a rollout cannot bring one back)."""
    cfg = _isolated()
    prefix = cfg.subjects[0].removesuffix("*")
    legacy = f"url4-cloud_{uuid4().hex}"
    nc, js = await _js()
    try:
        await js.add_stream(name=legacy, subjects=[f"{prefix}sometopic"])
        await ensure_events_stream(js, cfg, update=True)
        names = await _stream_names()
        assert legacy not in names and cfg.name in names
        with pytest.raises(APIError):
            await js.add_stream(name=legacy, subjects=[f"{prefix}othertopic"])
    finally:
        with contextlib.suppress(NotFoundError):
            await js.delete_stream(legacy)
        with contextlib.suppress(NotFoundError):
            await js.delete_stream(cfg.name)
        await nc.close()


async def test_purge_legacy_streams_deletes_only_the_per_run_prefix() -> None:
    """EVT-17 / EV-E3."""
    legacy = f"url4-cloud_{_topic('evt-17')}"
    stranger = f"stranger-{uuid4().hex[:8]}"
    nc, js = await _js()
    try:
        await js.add_stream(name=legacy, subjects=[f"legacy-{uuid4().hex}"])
        await js.add_stream(name=stranger, subjects=[f"stranger-{uuid4().hex}"])
        await ensure_events_stream(js, EventsStreamConfig(), update=False)

        listed = await purge_legacy_streams(js, dry_run=True)
        assert legacy in listed and stranger not in listed and EVENTS_STREAM not in listed
        assert legacy in await _stream_names()

        deleted = await purge_legacy_streams(js, dry_run=False)
        assert legacy in deleted
        names = await _stream_names()
        assert legacy not in names and stranger in names and EVENTS_STREAM in names
    finally:
        await js.delete_stream(stranger)
        await nc.close()


async def test_resume_on_a_live_run_that_lost_its_oldest_frames_continues_at_the_head() -> None:
    """A live run whose oldest frames were dropped (per-run cap, full store) is NOT over: a
    resume below the retained frames continues at the earliest one instead of reporting
    `stream_reclaimed`. Simulated with a subject purge that keeps the last 2 live frames."""
    topic = _topic("evt-rollover")
    child = JetStreamPublisher(NATS_URL)
    consumer = JetStreamConsumer(NATS_URL)
    nc, js = await _js()
    try:
        for n in range(1, 6):
            await child.publish(topic, _log(topic, n))
        await child.flush()
        await js.purge_stream(EVENTS_STREAM, subject=subject_for(topic), keep=2)
        frames = await _take(consumer, topic, 2, from_sequence=2)
        assert _seqs(frames) == [4, 5]
    finally:
        await child.close()
        await consumer.close()
        await nc.close()


async def test_a_run_whose_subject_already_ended_publishes_nothing() -> None:
    """I-EV4 on the child's side: the App's tombstone won the race against the claim, then the
    child starts anyway. Its frames must not land after the terminal frame."""
    topic = _topic("evt-late-child")
    app = JetStreamPublisher(NATS_URL)
    try:
        assert await app.publish_next(topic, _terminal(topic))
    finally:
        await app.close()
    await _mock_run(topic)
    assert [p for _, p in await _subject_state(topic)] == [1]


async def test_a_run_whose_first_frame_never_got_out_still_continues_the_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first frame's tail read failed (the run's failed arm publishes producer sequence 2
    next): the first frame this publisher STORES continues the subject, gap-free."""
    from screamingface_engine.adapters.jetstream import QueueReadError

    topic = _topic("evt-first-failed")
    first = JetStreamPublisher(NATS_URL)
    try:
        for n in range(1, 4):
            await first.publish(topic, _log(topic, n))
        await first.flush()
    finally:
        await first.close()
    child = JetStreamPublisher(NATS_URL)
    try:
        real_tail = child._tail  # noqa: SLF001

        async def broken_once(t: str):  # type: ignore[no-untyped-def]
            monkeypatch.setattr(child, "_tail", real_tail)
            raise QueueReadError("blip")

        monkeypatch.setattr(child, "_tail", broken_once)
        with pytest.raises(QueueReadError):
            await child.publish(topic, _log(topic, 1))
        await child.publish(topic, _terminal(topic, "failed").model_copy(update={"sequence": "2"}))
        await child.flush()
        assert [p for _, p in await _subject_state(topic)] == [1, 2, 3, 4]
    finally:
        await child.close()
