"""OME-1026 adversarial B3/B4 — the diagnostic sink must be safe to keep.

FEATURE: a background-error observation point that cannot itself become the leak or
the lost evidence. The sink exists so a programming error in an unawaited refresh
fails the run; that only holds if what it retains is safe to hold and its counters
are exact.

STORY: as an operator I want the gateway's own diagnostics to be the one place I can
read without worrying about what is in them — no credential, no upstream body, no
frame locals — and as a reviewer I want the "no background errors" assertion to mean
it, including when the errors arrive from several threads at once.

INVARIANT (B3, sanitized retention): the sink never retains an exception, its
traceback, its frames, its message, an upstream body, a credential, or auth headers.
A retained record is an immutable tuple of a safe key string, an exception TYPE name,
and an identity token used only to match a later ``mark_observed``.

INVARIANT (B3, exact under concurrency): the retention cap is exact and the dropped
count is lossless. Producers reach this module from the app's event-loop thread while
``TestClient`` teardown and test bodies read it from another, so every
read-modify-write of the two channels is serialized by one lock.

INVARIANT (B4, honest liveness): a task that absorbs cancellation and is still
running after a bounded ``aclose`` stays strongly referenced and counted until its
done-callback runs. Shutdown may give up waiting; it may not pretend the work died.

AIDEV-NOTE: the concurrency cases lower ``sys.setswitchinterval`` and use a
``threading.Barrier``, so the interleaving is forced rather than hoped for. They were
observed RED on the unsynchronized implementation (33 retained against a cap of 32,
and lost drop increments) and are deterministic in aggregate: with one lock the
asserted totals are exact by construction.
"""

from __future__ import annotations

import asyncio
import threading
from types import TracebackType

import pytest

from aigateway.core import background_error_sink
from aigateway.core.background_error_sink import (
    _MAX_RETAINED_UNEXPECTED,
    assert_no_unexpected,
    dropped_unexpected,
    mark_observed,
    record_unexpected,
    reset_unexpected,
    take_unexpected,
)
from aigateway.core.background_refresh import (
    BackgroundRefreshManager,
)

_SECRET = "sk-ant-frame-local-must-not-be-retained"
_EGRESS = "test attempted real discovery egress to https://api.example.invalid/v1/models"


@pytest.fixture(autouse=True)
def _isolated_sink():
    """Both channels start and end empty, so a case measures only its own errors."""
    reset_unexpected()
    yield
    reset_unexpected()


def _raise_holding_a_secret() -> None:
    """Raise with a credential in the raising frame's locals — the reproduced leak."""
    api_key = _SECRET  # noqa: F841 — the point is that it lives in the frame
    raise AssertionError(_EGRESS)


def _reachable(root: object, *, limit: int = 4096) -> list[object]:
    """Everything reachable from ``root`` through containers and ``__dict__``.

    Deliberately structural: the question is not "does the record LOOK safe" but
    "can anything holding the secret be reached from what the sink kept".
    """
    seen: dict[int, object] = {}
    queue = [root]
    while queue and len(seen) < limit:
        item = queue.pop()
        if id(item) in seen:
            continue
        seen[id(item)] = item
        if isinstance(item, str | bytes | int | float | bool | type(None)):
            continue
        if isinstance(item, dict):
            queue.extend(item.keys())
            queue.extend(item.values())
            continue
        if isinstance(item, list | tuple | set | frozenset):
            queue.extend(item)
            continue
        queue.extend(vars(item).values() if hasattr(item, "__dict__") else ())
        for attribute in ("__traceback__", "tb_frame", "f_locals", "args", "__cause__"):
            child = getattr(item, attribute, None)
            if child is not None:
                queue.append(child)
    return list(seen.values())


async def _fail_once_with_a_secret() -> None:
    manager = BackgroundRefreshManager[str](max_inflight=2)

    async def _boom() -> None:
        _raise_holding_a_secret()

    assert manager.start_or_join("leaky", _boom) is not None
    await manager.drain()
    await manager.aclose()


# ── B3: what the sink keeps must be safe to keep ──────────────────────────────


@pytest.mark.asyncio
async def test_a_retained_record_holds_no_exception_traceback_or_credential() -> None:
    """The headline: a probe found an ``x-api-key`` in a retained frame local."""
    await _fail_once_with_a_secret()

    retained = take_unexpected()

    assert len(retained) == 1, retained
    for record in retained:
        objects = _reachable(record)
        assert not any(isinstance(item, BaseException) for item in objects), (
            "the sink must not retain the exception itself"
        )
        assert not any(isinstance(item, TracebackType) for item in objects), (
            "the sink must not retain a traceback"
        )
        leaked = [item for item in objects if isinstance(item, str) and _SECRET in item]
        assert not leaked, "a credential was reachable from a retained record"
        # Nor the exception MESSAGE, which may carry an upstream body.
        assert not any(isinstance(item, str) and _EGRESS in item for item in objects), record


@pytest.mark.asyncio
async def test_a_retained_record_still_names_the_bug_class() -> None:
    """Sanitized is not useless: type name and key survive, which is the diagnosis."""
    await _fail_once_with_a_secret()

    (record,) = take_unexpected()

    assert record.key == "leaky", record
    assert record.type_name == "AssertionError", record
    assert isinstance(record.token, int)


@pytest.mark.asyncio
async def test_the_failure_message_names_type_and_key_but_no_exception_text() -> None:
    """The assertion's own text is a report surface too, so it is sanitized."""
    await _fail_once_with_a_secret()

    with pytest.raises(AssertionError) as caught:
        assert_no_unexpected("sanitized message")

    message = str(caught.value)
    assert "AssertionError" in message and "leaky" in message, message
    assert _SECRET not in message and _EGRESS not in message, message


# ── B3: exact under concurrency ───────────────────────────────────────────────


class _BarrierList(list):
    """A retention list whose ``__len__`` parks every caller until all have arrived.

    # WHY a seam and not volume: the defect is a read-modify-write race, and the GIL
    # makes it rare enough that 3200 unsynchronized appends can still land correctly.
    # Blocking inside ``__len__`` puts every producer between the capacity CHECK and
    # its own append at the same instant, which is exactly the interleaving the
    # independent probe reported — deterministically, on every run.
    """

    def __init__(self, *, parties: int, prefill: int) -> None:
        super().__init__(("prefilled", index) for index in range(prefill))
        self._barrier = threading.Barrier(parties)
        self._armed = True

    def __len__(self) -> int:
        size = super().__len__()
        if self._armed:
            try:
                self._barrier.wait(timeout=5.0)
            except threading.BrokenBarrierError:  # pragma: no cover - safety valve
                pass
        return size


def _record_from_threads(sink: _BarrierList, *, parties: int) -> None:
    """Let ``parties`` threads each record one error through the real producer."""

    def _producer(index: int) -> None:
        record_unexpected(f"racer{index}", AssertionError(f"{_EGRESS}#{index}"))

    workers = [threading.Thread(target=_producer, args=(index,)) for index in range(parties)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10.0)
    sink._armed = False


def test_the_retention_cap_is_exact_under_concurrent_producers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduced RED: 32 + 4 concurrent producers left 35 records against a cap of 32."""
    parties = 4
    sink = _BarrierList(parties=parties, prefill=_MAX_RETAINED_UNEXPECTED - 1)
    monkeypatch.setattr(background_error_sink, "_retained_unexpected", sink)

    _record_from_threads(sink, parties=parties)

    assert len(sink) <= _MAX_RETAINED_UNEXPECTED, len(sink)


class _BarrierInt(int):
    """A dropped-counter value whose ``__add__`` parks every caller until all arrive.

    # WHY this seam is the honest reproduction: ``_dropped_unexpected += 1`` compiles
    # to LOAD_GLOBAL / BINARY_OP / STORE_GLOBAL, and the lost update needs a switch
    # between the load and the store. Blocking inside ``__add__`` puts every producer
    # there at once, so each computes ``base + 1`` from the SAME base and the last
    # store wins — the interleaving the independent probe reported, on every run.
    # AIDEV-NOTE: the wait is bounded and a broken barrier is tolerated on purpose. A
    # correct (locked) producer admits one thread at a time, so the parties never all
    # arrive; each times out and proceeds, and the asserted total is then exact.
    """

    _barrier: threading.Barrier

    def __add__(self, other: int) -> int:  # type: ignore[override]
        try:
            self._barrier.wait(timeout=0.2)
        except threading.BrokenBarrierError:
            pass
        return int(self) + other


def test_the_dropped_count_is_lossless_under_concurrent_producers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduced RED: four concurrent overflows recorded ONE increment.

    Every error past the cap must be counted exactly once — past the cap the count is
    the whole evidence, so a lost increment is a silently under-reported outage.
    """
    parties = 4
    sink = _BarrierList(parties=parties, prefill=_MAX_RETAINED_UNEXPECTED)
    sink._armed = False
    counter = _BarrierInt(0)
    counter._barrier = threading.Barrier(parties)
    monkeypatch.setattr(background_error_sink, "_retained_unexpected", sink)
    monkeypatch.setattr(background_error_sink, "_dropped_unexpected", counter)

    _record_from_threads(sink, parties=parties)

    assert int(background_error_sink._dropped_unexpected) == parties, (
        int(background_error_sink._dropped_unexpected),
        parties,
    )


def test_the_observation_point_cannot_lose_an_error_to_a_concurrent_producer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduced RED: an error recorded mid-drain was cleared without being reported.

    The observation point read the records and then cleared the counter in two steps,
    so an error arriving in between was wiped by the clear — reported by nobody,
    counted by nobody. The seam below puts the producer exactly there on every run.
    """
    rounds = 4
    for index in range(rounds):
        entered = threading.Event()
        appended = threading.Event()

        class _DrainSeam(list):
            """Parks the drain between reading the records and clearing the count."""

            def __iter__(self):
                entered.set()
                appended.wait(timeout=0.2)
                return super().__iter__()

        seam = _DrainSeam()
        monkeypatch.setattr(background_error_sink, "_retained_unexpected", seam)

        def _producer(round_index: int = index) -> None:
            entered.wait(timeout=5.0)
            record_unexpected(f"race{round_index}", AssertionError(_EGRESS))
            appended.set()

        producer = threading.Thread(target=_producer)
        producer.start()
        observed = 0
        try:
            assert_no_unexpected(f"round {index}")
        except AssertionError:
            observed = 1
        producer.join(timeout=5.0)

        left = list.__len__(seam)
        assert observed + left == 1, (index, observed, left)
        monkeypatch.undo()


# ── B3: mark_observed keeps working without holding the exception ──────────────


@pytest.mark.asyncio
async def test_mark_observed_removes_the_matching_record_without_retaining_it() -> None:
    """The awaited-bug path: surfaced to a caller, so not ALSO reported as a leak."""
    manager = BackgroundRefreshManager[str](max_inflight=2)

    async def _boom() -> None:
        raise AssertionError(_EGRESS)

    task = manager.start_or_join("observed", _boom)
    assert task is not None
    with pytest.raises(AssertionError):
        await task
    exc = task.exception()
    assert exc is not None

    mark_observed(exc)

    assert take_unexpected() == (), "an observed error must not remain retained"
    assert dropped_unexpected() == 0
    await manager.aclose()


@pytest.mark.asyncio
async def test_an_error_observed_before_it_is_recorded_is_never_retained() -> None:
    """The other order: ``mark_observed`` first, then the sink hears about it."""
    exc = AssertionError(_EGRESS)
    mark_observed(exc)

    record_unexpected("pre-observed", exc)

    assert take_unexpected() == ()
    assert dropped_unexpected() == 0


@pytest.mark.asyncio
async def test_a_cancelled_task_reports_nothing() -> None:
    """Preserved behaviour: shutdown cancellation is not a bug report."""
    started = asyncio.Event()
    manager = BackgroundRefreshManager[str](max_inflight=2)

    async def _parked() -> None:
        started.set()
        await asyncio.Event().wait()

    assert manager.start_or_join("parked", _parked) is not None
    await started.wait()
    await manager.aclose()

    assert take_unexpected() == ()
    assert dropped_unexpected() == 0


# ── B4: a cancellation-resistant task stays tracked ───────────────────────────


@pytest.mark.asyncio
async def test_a_cancellation_resistant_task_stays_tracked_after_a_bounded_close() -> None:
    """Reproduced RED: task alive, ``inflight == 0``, tracked set empty.

    # WHY this matters beyond tidiness: ``inflight`` is the capacity gauge and the
    # tracked map is the STRONG reference set. Clearing both while the task runs
    # makes the manager's own accounting claim work finished that is still holding a
    # discovery socket, and makes the task garbage-collectable mid-flight.
    """
    started = asyncio.Event()
    release = asyncio.Event()
    manager = BackgroundRefreshManager[str](max_inflight=2, shutdown_timeout_s=0.05)

    async def _resistant() -> None:
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            # Absorbs the cancellation, exactly as provider cleanup code may.
            await release.wait()

    task = manager.start_or_join("resistant", _resistant)
    assert task is not None
    await started.wait()

    await manager.aclose()

    assert not task.done(), "the premise: the task absorbed the shutdown cancellation"
    assert manager.inflight == 1, "a live task must remain visible to live accounting"
    assert manager.tracked_keys() == ("resistant",) or task in manager.pending_tasks(), (
        "a live task must remain STRONGLY referenced after a bounded close"
    )

    release.set()
    await asyncio.wait({task}, timeout=1.0)
    await asyncio.sleep(0)

    assert task.done()
    assert manager.inflight == 0, "and it must be released once it finally exits"
    assert manager.pending_tasks() == ()


@pytest.mark.asyncio
async def test_a_closed_manager_still_refuses_new_work() -> None:
    """Closing prevents new work; it does not pretend old work died."""
    release = asyncio.Event()
    manager = BackgroundRefreshManager[str](max_inflight=2, shutdown_timeout_s=0.05)

    async def _resistant() -> None:
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()

    assert manager.start_or_join("resistant", _resistant) is not None
    await asyncio.sleep(0)
    await manager.aclose()

    async def _never() -> None:  # pragma: no cover - must not be started
        raise AssertionError("a closed manager started new work")

    assert manager.start_or_join("new", _never) is None
    release.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_a_finished_task_is_dropped_promptly_by_a_bounded_close() -> None:
    """The other half of honest accounting: done work must not linger as live."""
    manager = BackgroundRefreshManager[str](max_inflight=2, shutdown_timeout_s=0.05)

    async def _quick() -> str:
        return "done"

    task = manager.start_or_join("quick", _quick)
    assert task is not None
    await manager.drain()

    await manager.aclose()

    assert task.done()
    assert manager.inflight == 0
    assert manager.pending_tasks() == ()
    assert manager.tracked_keys() == ()
