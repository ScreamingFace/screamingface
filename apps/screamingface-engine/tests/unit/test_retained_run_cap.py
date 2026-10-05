"""A retained (failed/timed_out) run's subject is capped, by messages AND bytes (OME-1462).

FEATURE: post-mortem of a failed run (OME-946) without letting a failure storm fill the shared
`url4-events` stream. Owner decision (2026-10-02): a per-subject cap for retained runs, no
separate stream. The stream is `discard=OLD` at 1 GiB; an uncapped retained subject could hold
up to 20 000 frames of up to 2 MiB each, and the eviction that follows hits the OLDEST frames
of ANY subject — including other runs' terminal frames, which dedupe and admission read.

INVARIANT: the trim never removes a subject's last (terminal) frame, even when that frame
alone is over the byte budget.

STORY: as an operator, a failed run's last frames are still there an hour later; as an owner,
a storm of failures cannot cost more than the cap per run.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js.errors import NotFoundError

from screamingface_engine.adapters.jetstream import (
    EventsStreamConfig,
    JetStreamPublisher,
    retained_cut,
)
from screamingface_engine.evidence_retention import subject_retained
from screamingface_engine.runner.main import run_and_reclaim
from screamingface_engine.subjects import subject_for
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

pytestmark = pytest.mark.asyncio

TOPIC = "capped"


# --- the cut: which stream sequence the byte budget keeps from --------------------------------


@pytest.mark.parametrize(
    ("sizes", "budget", "cut"),
    [
        pytest.param([], 100, None, id="empty-subject"),
        pytest.param([(1, 100), (2, 100), (3, 100)], 300, None, id="exactly-at-budget"),
        pytest.param([(1, 100), (2, 100), (3, 100)], 299, 2, id="one-byte-over"),
        pytest.param([(1, 100), (2, 100), (3, 100)], 100, 3, id="tail-only"),
        pytest.param([(1, 10), (2, 10), (3, 500)], 50, 3, id="tail-alone-over-budget"),
        pytest.param([(5, 10), (9, 10), (14, 10)], 25, 9, id="sparse-stream-sequences"),
        pytest.param([(7, 4096)], 1, None, id="a-lone-frame-is-never-cut"),
    ],
)
async def test_the_cut_keeps_the_newest_frames_that_fit(
    sizes: list[tuple[int, int]], budget: int, cut: int | None
) -> None:
    assert retained_cut(sizes, budget) == cut


async def test_the_cut_never_removes_the_terminal_frame() -> None:
    """INVARIANT: the tail survives every budget, including zero."""
    sizes = [(1, 10), (2, 10), (3, 10)]
    for budget in (0, 1, 9, 10, 29, 30):
        cut = retained_cut(sizes, budget)
        assert cut is None or cut <= 3


# --- the trim against a JetStream context -----------------------------------------------------


def _not_found() -> NotFoundError:
    return NotFoundError(code=404, err_code=10037, description="no message found")


class _FakeJs:
    """The JetStream calls `trim_retained` makes, against an in-memory stream that applies
    purge `keep` / `seq` with a subject filter the way the broker does."""

    def __init__(self, messages: list[tuple[str, bytes]], *, stream_exists: bool = True) -> None:
        self.messages = [(seq, subj, data) for seq, (subj, data) in enumerate(messages, start=1)]
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._exists = stream_exists

    async def purge_stream(
        self,
        name: str,
        seq: int | None = None,
        subject: str | None = None,
        keep: int | None = None,
    ) -> bool:
        self.calls.append(("purge", {"seq": seq, "subject": subject, "keep": keep}))
        if not self._exists:
            raise NotFoundError(code=404, err_code=10059, description="stream not found")
        mine = [m for m in self.messages if m[1] == subject]
        if keep is not None:
            doomed = mine[: max(len(mine) - keep, 0)]
        else:
            assert seq is not None
            doomed = [m for m in mine if m[0] < seq]
        self.messages = [m for m in self.messages if m not in doomed]
        return True

    async def get_msg(
        self,
        stream_name: str,
        seq: int | None = None,
        subject: str | None = None,
        direct: bool = False,
        next: bool = False,
    ) -> Any:
        assert next, "the scan walks forward with next_by_subj"
        self.calls.append(("get", {"seq": seq}))
        for s, subj, data in self.messages:
            if subj == subject and s >= (seq or 0):
                return SimpleNamespace(seq=s, data=data)
        raise _not_found()


def _publisher(
    js: _FakeJs, *, retained_max_msgs: int = 256, retained_max_bytes: int = 1024**2
) -> JetStreamPublisher:
    config = EventsStreamConfig(
        retained_max_msgs=retained_max_msgs, retained_max_bytes=retained_max_bytes
    )
    pub = JetStreamPublisher("nats://unused", events=config)
    pub._js = cast(Any, js)  # noqa: SLF001 - a context without a dial, as `_is_closed` allows
    return pub


def _kept(js: _FakeJs, subject: str) -> list[bytes]:
    return [data for _, subj, data in js.messages if subj == subject]


async def test_the_defaults_cap_a_retained_subject_at_256_frames_and_1_mib() -> None:
    config = EventsStreamConfig()
    assert config.retained_max_msgs == 256
    assert config.retained_max_bytes == 1024**2


async def test_the_message_cap_is_applied_by_the_broker_with_keep() -> None:
    subject = subject_for(TOPIC)
    js = _FakeJs([(subject, b"x") for _ in range(10)])

    await _publisher(js, retained_max_msgs=4, retained_max_bytes=1024).trim_retained(TOPIC)

    assert js.calls[0] == ("purge", {"seq": None, "subject": subject, "keep": 4})
    assert len(_kept(js, subject)) == 4


async def test_the_byte_cap_drops_the_oldest_survivors_and_keeps_the_tail() -> None:
    subject = subject_for(TOPIC)
    js = _FakeJs([(subject, b"a" * 40), (subject, b"b" * 40), (subject, b"c" * 40)])

    await _publisher(js, retained_max_msgs=10, retained_max_bytes=100).trim_retained(TOPIC)

    assert _kept(js, subject) == [b"b" * 40, b"c" * 40]


async def test_other_subjects_are_never_touched() -> None:
    """The cap is PER SUBJECT: a neighbour's frames (sharing the stream) survive the trim."""
    subject, other = subject_for(TOPIC), subject_for("neighbour")
    js = _FakeJs([(other, b"n" * 90), (subject, b"a" * 90), (subject, b"b" * 90), (other, b"m")])

    await _publisher(js, retained_max_msgs=10, retained_max_bytes=100).trim_retained(TOPIC)

    assert _kept(js, subject) == [b"b" * 90]
    assert _kept(js, other) == [b"n" * 90, b"m"]


async def test_a_subject_under_both_caps_gets_no_second_purge() -> None:
    subject = subject_for(TOPIC)
    js = _FakeJs([(subject, b"a"), (subject, b"b")])

    await _publisher(js, retained_max_msgs=10, retained_max_bytes=100).trim_retained(TOPIC)

    assert [c for c, _ in js.calls].count("purge") == 1
    assert _kept(js, subject) == [b"a", b"b"]


async def test_an_oversized_terminal_frame_alone_survives() -> None:
    subject = subject_for(TOPIC)
    js = _FakeJs([(subject, b"a"), (subject, b"T" * 500)])

    await _publisher(js, retained_max_msgs=10, retained_max_bytes=100).trim_retained(TOPIC)

    assert _kept(js, subject) == [b"T" * 500]


async def test_the_scan_is_bounded_by_the_message_cap() -> None:
    """The scan runs on a reclaim task; it reads at most `retained_max_msgs` frames (plus the
    one miss that ends it), never the subject's pre-trim length."""
    subject = subject_for(TOPIC)
    js = _FakeJs([(subject, b"x") for _ in range(50)])

    await _publisher(js, retained_max_msgs=5, retained_max_bytes=1024).trim_retained(TOPIC)

    assert [c for c, _ in js.calls].count("get") <= 6


async def test_a_missing_stream_is_nothing_to_trim() -> None:
    js = _FakeJs([], stream_exists=False)

    await _publisher(js).trim_retained(TOPIC)

    assert [c for c, _ in js.calls] == ["purge"]


# --- the reclaim paths trim a retained run instead of skipping it ----------------------------


def _terminated(status: Any) -> TerminatedEvent:
    return TerminatedEvent(
        id="t", source=source_for(TOPIC), subject=TOPIC, data=TerminatedData(status=status)
    )


class _Recorder:
    def __init__(self, tail: Any) -> None:
        self.tail = tail
        self.events: list[str] = []

    async def sleep(self, seconds: float) -> None:
        self.events.append("slept")

    async def last_frame(self, topic: str) -> Any:
        return self.tail

    async def delete_stream(self, topic: str) -> None:
        self.events.append(f"deleted:{topic}")

    async def trim(self, topic: str) -> None:
        self.events.append(f"trimmed:{topic}")


async def _ran() -> None:
    return None


@pytest.mark.parametrize("status", ["failed", "timed_out"])
async def test_the_runner_trims_a_retained_run_and_never_deletes_it(status: str) -> None:
    rec = _Recorder(_terminated(status))

    await run_and_reclaim(
        cast(JetStreamPublisher, cast(Any, rec)),
        TOPIC,
        _ran,
        grace_s=0.0,
        sleep=rec.sleep,
        retain=lambda t: subject_retained(rec.last_frame, t),
        trim=rec.trim,
    )

    assert rec.events == ["slept", f"trimmed:{TOPIC}"]


async def test_the_runner_purges_a_successful_run_and_never_trims_it() -> None:
    rec = _Recorder(_terminated("succeeded"))

    await run_and_reclaim(
        cast(JetStreamPublisher, cast(Any, rec)),
        TOPIC,
        _ran,
        grace_s=0.0,
        sleep=rec.sleep,
        retain=lambda t: subject_retained(rec.last_frame, t),
        trim=rec.trim,
    )

    assert rec.events == ["slept", f"deleted:{TOPIC}"]


async def test_a_raising_trim_never_masks_the_runs_outcome() -> None:
    """D5: the trim is best-effort like the purge it replaces; `max_age` is the backstop."""
    rec = _Recorder(_terminated("failed"))

    async def _boom() -> None:
        raise RuntimeError("the real failure")

    async def _broken_trim(topic: str) -> None:
        raise NatsTimeoutError

    with pytest.raises(RuntimeError, match="the real failure"):
        await run_and_reclaim(
            cast(JetStreamPublisher, cast(Any, rec)),
            TOPIC,
            _boom,
            grace_s=0.0,
            sleep=rec.sleep,
            retain=lambda t: subject_retained(rec.last_frame, t),
            trim=_broken_trim,
        )


# --- minor 3: an unknown failure reading the tail is an unknown ending -----------------------


async def test_any_failure_to_read_the_tail_falls_back_to_the_purge() -> None:
    """The documented rule — an unknown ending must not extend a possibly SUCCESSFUL run's
    prompt-bearing frames — held only for `QueueReadError`. A connect that fails with an
    `OSError` (or anything else) left the subject for `max_age` instead of purging it."""

    async def last_frame(topic: str) -> Any:
        raise ConnectionRefusedError("broker down")

    assert await subject_retained(last_frame, TOPIC) is False


async def test_a_cancelled_tail_read_is_not_swallowed() -> None:
    """The widening is to `Exception`, never `BaseException`: a cancelled reclaim (the worker
    stopping) must still unwind."""

    async def last_frame(topic: str) -> Any:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await subject_retained(last_frame, TOPIC)


# --- the worker path (RECLAIM_OWNER=worker) --------------------------------------------------


class _WorkerPublisher:
    def __init__(self, tail: Any) -> None:
        self.tail = tail

    async def last_frame(self, topic: str) -> Any:
        return self.tail


def _supervisor(tail: Any, events: list[str]) -> Any:
    from screamingface_engine.worker.loop import Worker

    async def reclaim(topic: str) -> None:
        events.append(f"deleted:{topic}")

    async def trim(topic: str) -> None:
        events.append(f"trimmed:{topic}")

    worker = Worker(
        queue=SimpleNamespace(),  # type: ignore[arg-type]
        publisher=_WorkerPublisher(tail),  # type: ignore[arg-type]
        slots=1,
        drain_grace_s=0.1,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        spawn=lambda *a, **k: None,  # type: ignore[arg-type,return-value]
        trim_retained=trim,
    )
    supervisor = worker._supervisor  # noqa: SLF001 - the seam under test
    supervisor._reclaim = reclaim  # noqa: SLF001 - the seam under test
    return supervisor


@pytest.mark.parametrize(
    ("status", "expected"),
    [("failed", "trimmed"), ("timed_out", "trimmed"), ("succeeded", "deleted")],
)
async def test_the_worker_trims_a_retained_run_and_purges_the_rest(
    status: str, expected: str
) -> None:
    events: list[str] = []
    supervisor = _supervisor(_terminated(status), events)

    supervisor._schedule_reclaim(TOPIC, {"URL4_CLOUD_STREAM_GRACE_S": "0"})  # noqa: SLF001
    await asyncio.gather(*tuple(supervisor._reclaims))  # noqa: SLF001

    assert events == [f"{expected}:{TOPIC}"]
