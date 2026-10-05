"""Failed runs keep their frames; successful runs are reclaimed at the grace (OME-946).

FEATURE: post-mortem of a failed deployed run. A run's frames on the shared `url4-events`
stream are its whole diagnostic record, and both reclaim paths purged them `STREAM_GRACE_S`
(60 s) after the run ended — so a failed run was unreconstructable within a minute. Now a
subject whose terminal frame says `failed` or `timed_out` is left for the stream's 24 h
`max_age` to reap; every other ending keeps the 60 s purge (cost + prompt-content exposure:
the stream carries full bodies).

STORY: as an operator debugging a run that failed an hour ago, I can still replay its frames.
"""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from screamingface_engine import job_env
from screamingface_engine.adapters.jetstream import JetStreamPublisher, QueueReadError
from screamingface_engine.evidence_retention import (
    RETAINED_STATUSES,
    retains_evidence,
    subject_retained,
)
from screamingface_engine.runner.main import run_and_reclaim
from screamingface_engine.worker.loop import Worker
from url4.streaming.protocol import (
    ResultData,
    ResultEvent,
    TerminatedData,
    TerminatedEvent,
    source_for,
)

pytestmark = pytest.mark.asyncio


def _terminated(topic: str, status: Any) -> TerminatedEvent:
    return TerminatedEvent(
        id=f"term-{topic}",
        source=source_for(topic),
        subject=topic,
        data=TerminatedData(status=status),
    )


def _result(topic: str) -> ResultEvent:
    return ResultEvent(
        id=f"res-{topic}", source=source_for(topic), subject=topic, data=ResultData(body="x")
    )


# --- the rule ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "retained"),
    [("failed", True), ("timed_out", True), ("succeeded", False), ("stopped", False)],
)
async def test_only_failed_and_timed_out_endings_retain_evidence(
    status: str, retained: bool
) -> None:
    """INVARIANT: the retained set is exactly {failed, timed_out}. `stopped` is an owner's
    cancel or a drain — not a failure to investigate — and keeps the purge like a success."""
    assert retains_evidence(_terminated("t", status)) is retained


async def test_the_retained_set_is_exactly_failed_and_timed_out() -> None:
    assert frozenset({"failed", "timed_out"}) == RETAINED_STATUSES


async def test_a_subject_without_a_terminal_frame_is_purged() -> None:
    """No terminal frame proves no failure; the status quo (purge) stands."""
    assert retains_evidence(None) is False
    assert retains_evidence(_result("t")) is False


async def test_the_subject_is_retained_when_its_tail_reads_failed() -> None:
    async def last_frame(topic: str) -> Any:
        return _terminated(topic, "failed")

    assert await subject_retained(last_frame, "t") is True


async def test_an_unreadable_tail_falls_back_to_the_purge() -> None:
    """WHY purge on an unreadable tail: retention must never extend a SUCCESSFUL run's
    prompt-bearing frames by accident; an unknown ending gets the pre-OME-946 behaviour."""

    async def last_frame(topic: str) -> Any:
        raise QueueReadError("broker blip")

    assert await subject_retained(last_frame, "t") is False


# --- the worker path (RECLAIM_OWNER=worker) ------------------------------------------------


class _Msg:
    def __init__(self, topic: str, deadline_s: float = 60, grace_s: str = "0.1") -> None:
        self.data = json.dumps(
            {
                job_env.TOPIC: topic,
                job_env.EXPRESSION: "'hi'",
                job_env.JOB_DEADLINE_S: str(deadline_s),
                job_env.STREAM_GRACE_S: grace_s,
            }
        ).encode()
        self.metadata = SimpleNamespace(timestamp=datetime.now(UTC))
        self.headers = None
        self.acked = False

    async def ack(self) -> None:
        self.acked = True

    async def in_progress(self) -> None:
        pass


class _Publisher:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def last_frame(self, topic: str) -> Any:
        return self.published[-1] if self.published else None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _Proc:
    """A child that, on exit, optionally publishes its own terminal frame first."""

    def __init__(
        self,
        publisher: _Publisher,
        topic: str,
        *,
        own_status: str | None = None,
        exit_code: int | None = 0,
    ) -> None:
        self._publisher, self._topic = publisher, topic
        self._own_status, self._exit_code = own_status, exit_code
        self._done = asyncio.Event()
        self.returncode: int | None = None
        self.stdout = self.stderr = None

    async def wait(self) -> int:
        if self._exit_code is not None and self.returncode is None:
            if self._own_status is not None:
                await self._publisher.publish(
                    self._topic, _terminated(self._topic, self._own_status)
                )
            self._finish(self._exit_code)
        await self._done.wait()
        assert self.returncode is not None
        return self.returncode

    def _finish(self, code: int) -> None:
        if self.returncode is None:
            self.returncode = code
        self._done.set()

    def terminate(self) -> None:
        self._finish(-15)

    def kill(self) -> None:
        self._finish(-9)


class _Launcher:
    def __init__(self, proc: Any) -> None:
        self._proc = proc

    async def launch(self, env: Any, *, io_budget: Any) -> Any:
        return self._proc


def _worker(publisher: _Publisher, proc: _Proc, reclaimed: list[str]) -> Worker:
    worker = Worker(
        queue=SimpleNamespace(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        slots=1,
        drain_grace_s=0.1,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        spawn=lambda *a, **k: None,  # type: ignore[arg-type,return-value]
        deadline_margin_s=0.05,
        kill_grace_s=0.05,
    )
    worker._supervisor._launcher = _Launcher(proc)  # noqa: SLF001 - the seam under test

    async def reclaim(topic: str) -> None:
        reclaimed.append(topic)

    worker._supervisor._reclaim = reclaim  # noqa: SLF001 - the seam under test
    return worker


async def _supervise_and_outlive_grace(worker: Worker, msg: _Msg) -> None:
    await worker._supervisor.supervise(msg)  # type: ignore[arg-type]
    assert msg.acked
    await asyncio.sleep(0.3)  # well past the 0.1 s grace


async def test_the_worker_reclaims_a_successful_run_after_the_grace() -> None:
    publisher, reclaimed = _Publisher(), []
    worker = _worker(publisher, _Proc(publisher, "t-ok", own_status="succeeded"), reclaimed)
    await _supervise_and_outlive_grace(worker, _Msg("t-ok"))
    assert reclaimed == ["t-ok"]


async def test_the_worker_keeps_a_run_the_child_reported_failed() -> None:
    """The child published `Terminated(failed)` itself and exited 0 — the common failure
    shape (`lifecycle.run` returns normally on failure). Only the tail can tell."""
    publisher, reclaimed = _Publisher(), []
    worker = _worker(publisher, _Proc(publisher, "t-fail", own_status="failed"), reclaimed)
    await _supervise_and_outlive_grace(worker, _Msg("t-fail"))
    assert reclaimed == []


async def test_the_worker_keeps_a_run_whose_child_crashed() -> None:
    """A non-zero exit gets the worker's own classified `failed` frame — retained too."""
    publisher, reclaimed = _Publisher(), []
    worker = _worker(publisher, _Proc(publisher, "t-crash", exit_code=3), reclaimed)
    await _supervise_and_outlive_grace(worker, _Msg("t-crash"))
    assert publisher.published[-1].data.status == "failed"
    assert reclaimed == []


async def test_the_worker_keeps_a_run_that_timed_out() -> None:
    publisher, reclaimed = _Publisher(), []
    worker = _worker(publisher, _Proc(publisher, "t-slow", exit_code=None), reclaimed)
    await _supervise_and_outlive_grace(worker, _Msg("t-slow", deadline_s=0.1, grace_s="0"))
    assert publisher.published[-1].data.status == "timed_out"
    assert reclaimed == []


async def test_the_worker_still_reclaims_a_cancelled_run() -> None:
    """`stopped` is not a failure: an owner's cancel keeps the 60 s purge."""
    publisher, reclaimed = _Publisher(), []
    worker = _worker(publisher, _Proc(publisher, "t-stop", own_status="stopped"), reclaimed)
    await _supervise_and_outlive_grace(worker, _Msg("t-stop"))
    assert reclaimed == ["t-stop"]


# --- the runner path (no pool: the runner reclaims its own subject) -------------------------


class _Recorder:
    def __init__(self, tail: Any = None) -> None:
        self.events: list[str] = []
        self.tail = tail

    async def sleep(self, seconds: float) -> None:
        self.events.append(f"slept:{seconds}")

    async def last_frame(self, topic: str) -> Any:
        return self.tail

    async def delete_stream(self, topic: str) -> None:
        self.events.append(f"deleted:{topic}")


def _publisher(rec: _Recorder) -> JetStreamPublisher:
    return cast(JetStreamPublisher, cast(Any, rec))


def _retain(rec: _Recorder) -> Any:
    return lambda topic: subject_retained(rec.last_frame, topic)


async def test_the_runner_keeps_a_failed_run() -> None:
    rec = _Recorder(tail=_terminated("t", "failed"))

    async def _run() -> None:
        rec.events.append("ran")

    await run_and_reclaim(
        _publisher(rec), "t", _run, grace_s=60.0, sleep=rec.sleep, retain=_retain(rec)
    )
    assert rec.events == ["ran", "slept:60.0"]


async def test_the_runner_keeps_a_timed_out_run_and_reraises_its_failure() -> None:
    rec = _Recorder(tail=_terminated("t", "timed_out"))

    async def _boom() -> None:
        raise RuntimeError("the real failure")

    with pytest.raises(RuntimeError, match="the real failure"):
        await run_and_reclaim(
            _publisher(rec), "t", _boom, grace_s=1.0, sleep=rec.sleep, retain=_retain(rec)
        )
    assert rec.events == ["slept:1.0"]


async def test_the_runner_reclaims_a_successful_run_at_the_grace() -> None:
    rec = _Recorder(tail=_terminated("t", "succeeded"))

    async def _run() -> None:
        rec.events.append("ran")

    await run_and_reclaim(
        _publisher(rec), "t", _run, grace_s=60.0, sleep=rec.sleep, retain=_retain(rec)
    )
    assert rec.events == ["ran", "slept:60.0", "deleted:t"]


async def test_a_raising_retention_check_does_not_mask_the_run_outcome() -> None:
    """INVARIANT (inherited from the teardown): nothing in the reclaim `finally` escapes."""
    rec = _Recorder()

    async def _run() -> None:
        rec.events.append("ran")

    async def _broken(topic: str) -> bool:
        raise RuntimeError("unexpected")

    await run_and_reclaim(_publisher(rec), "t", _run, grace_s=0.0, sleep=rec.sleep, retain=_broken)
    assert rec.events == ["ran", "slept:0.0"]
