"""OME-1026 last-mile — the sink's observed-marker and its record are ONE fact.

FEATURE: a background-error observation point whose verdict is trustworthy in both
directions. "This error was observed" and "this error is still retained" must never
disagree, or the suite fails a run for an error a caller already handled — and a
false teardown failure trains everyone to ignore the one assertion that catches a
real leak.

STORY: as the engineer whose test deliberately awaits a failing refresh and asserts
on it, I want teardown to stay silent, because I observed that error; and as the
reviewer of a refresh nobody awaited, I want teardown to still fail.

INVARIANT (last-mile Blocker 2): the observed marker and the retained record are
mutated under ONE lock, so the pair has a single linearization point. If observation
linearizes first the producer must not append; if recording linearizes first the
observation must remove that record. There is no schedule that leaves a record for an
observed error.

AIDEV-NOTE: the reproduction is a seam, not a volume loop. The defect needs a thread
switch between the producer's marker CHECK and its append, and the GIL serializes
that pair often enough that repetition alone stays green. ``_SeamLock`` parks one
designated thread at its first lock entry, which is the check/append boundary on the
unsynchronized code and the pre-check boundary on the fixed code — so the same test
drives both, deterministically, on every run.
"""

from __future__ import annotations

import gc
import threading
from types import FrameType, ModuleType, TracebackType

import pytest

from aigateway.core import background_error_sink
from aigateway.core.background_error_sink import (
    _MAX_RETAINED_UNEXPECTED,
    UnexpectedRecord,
    assert_no_unexpected,
    drain_unexpected,
    dropped_unexpected,
    mark_observed,
    record_unexpected,
    reset_unexpected,
    take_unexpected,
)

_TIMEOUT = 5.0
_SECRET = "sk-ant-observation-race-must-not-be-retained"
_UPSTREAM = "upstream said: quota exceeded for organization org-12345"


@pytest.fixture(autouse=True)
def _isolated_sink():
    """Both channels start and end empty, so a case measures only its own errors."""
    reset_unexpected()
    yield
    reset_unexpected()


class _SeamLock:
    """The real sink lock, with one designated thread parked at its first entry.

    # WHY the park happens BEFORE acquiring the real lock: the other party must be
    # able to run its own locked section while this one is parked. Parking while
    # holding the lock would deadlock the schedule instead of interleaving it — and
    # on the fixed code this point is where the marker check now lives, which is
    # exactly the boundary the defect needs.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._armed_for: str | None = None
        self.reached = threading.Event()
        self.release = threading.Event()

    def arm_for(self, thread_name: str) -> None:
        self._armed_for = thread_name

    def __enter__(self) -> _SeamLock:
        if self._armed_for is not None and threading.current_thread().name == self._armed_for:
            self._armed_for = None  # one-shot: later sections run unimpeded
            self.reached.set()
            assert self.release.wait(timeout=_TIMEOUT), "the parked seam was never released"
        self._lock.acquire()
        return self

    def __exit__(self, *_exc: object) -> bool:
        self._lock.release()
        return False


def _install_seam(monkeypatch: pytest.MonkeyPatch, *, park_thread: str) -> _SeamLock:
    seam = _SeamLock()
    seam.arm_for(park_thread)
    monkeypatch.setattr(background_error_sink, "_sink_lock", seam)
    return seam


def _run_in_thread(name: str, target) -> threading.Thread:
    worker = threading.Thread(target=target, name=name)
    worker.start()
    return worker


# ── the two legal orders ───────────────────────────────────────────────────────


def test_an_observation_that_linearizes_first_leaves_no_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED on the unsynchronized sink: the record outlived the observation.

    The reproduced schedule, forced rather than hoped for::

        producer checks the marker (False)  <- outside the lock on the old code
        observer sets the marker and scans an EMPTY list
        producer appends its record         <- nobody will ever remove it

    The caller already observed this error, so a retained record here is a FALSE
    teardown failure — the exact defect the independent probe reported.
    """
    exc = AssertionError(_UPSTREAM)
    seam = _install_seam(monkeypatch, park_thread="producer")

    producer = _run_in_thread("producer", lambda: record_unexpected("raced", exc))
    assert seam.reached.wait(timeout=_TIMEOUT), "the producer never reached the sink lock"

    mark_observed(exc)  # linearizes FIRST, while the producer is parked at the seam

    seam.release.set()
    producer.join(timeout=_TIMEOUT)
    assert not producer.is_alive()

    assert take_unexpected() == (), "an observed error must not be retained by a late producer"
    assert dropped_unexpected() == 0


def test_a_record_that_linearizes_first_is_removed_by_the_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other legal order, forced the same way: the observation must clean up.

    Parking the OBSERVER at the seam puts the append strictly before the marker
    transition, which is the order the done-callback actually produces (it runs
    before the awaiting caller resumes).
    """
    exc = AssertionError(_UPSTREAM)
    seam = _install_seam(monkeypatch, park_thread="observer")

    observer = _run_in_thread("observer", lambda: mark_observed(exc))
    assert seam.reached.wait(timeout=_TIMEOUT), "the observer never reached the sink lock"

    record_unexpected("raced", exc)  # linearizes FIRST, while the observer is parked

    seam.release.set()
    observer.join(timeout=_TIMEOUT)
    assert not observer.is_alive()

    assert take_unexpected() == (), "the observation must remove the record it found"
    assert dropped_unexpected() == 0


# ── preserved behaviour the fix must not disturb ───────────────────────────────


def test_concurrent_overflow_retains_exactly_the_cap_and_counts_every_drop() -> None:
    """The cap is EXACT and the dropped count lossless when producers arrive together.

    Every producer is released from one barrier, so the contention is real; with a
    single linearization point the two channels still sum to the number of errors.
    """
    surplus = 8
    total = _MAX_RETAINED_UNEXPECTED + surplus
    # INVARIANT: the exceptions stay referenced for the whole case. The retained token
    # is ``id(exc)``, which is only unambiguous while the object is alive.
    errors = [AssertionError(f"{_UPSTREAM}#{index}") for index in range(total)]
    gate = threading.Barrier(total)

    def _producer(index: int) -> None:
        gate.wait(timeout=_TIMEOUT)
        record_unexpected(f"overflow{index}", errors[index])

    workers = [_run_in_thread(f"p{index}", lambda i=index: _producer(i)) for index in range(total)]
    for worker in workers:
        worker.join(timeout=_TIMEOUT * 2)
        assert not worker.is_alive()

    retained, dropped = drain_unexpected()
    assert len(retained) == _MAX_RETAINED_UNEXPECTED, len(retained)
    assert dropped == surplus, dropped
    assert len(retained) + dropped == total
    assert len({record.token for record in retained}) == len(retained), "tokens must be distinct"


def test_a_record_produced_through_the_race_reaches_no_exception_or_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanitization is not weakened by the linearization: the record graph stays flat.

    # WHY ``gc.get_referents`` rather than an attribute walk: it asks the interpreter
    # what the object actually holds, so a future field that references a frame — the
    # reproduced leak — cannot hide behind a dunder this test forgot to follow.
    # AIDEV-NOTE: the walk skips ``type`` and module edges on purpose, and that is not
    # a loophole. CPython's ``subtype_traverse`` makes every heap-subclass instance
    # visit its own class, so following that edge reaches the class dict, its methods'
    # code objects, their module globals — i.e. the whole interpreter, including this
    # file's source constants. The class is shared, static, and holds no per-error
    # state; the leak class under test is per-error DATA hanging off the value, which
    # is what the field-type assertion below bounds exactly.
    """

    def _raise_holding_a_secret() -> AssertionError:
        api_key = _SECRET  # noqa: F841 — the point is that it lives in this frame
        assert api_key
        try:
            raise AssertionError(_UPSTREAM)
        except AssertionError as caught:
            return caught

    exc = _raise_holding_a_secret()
    assert exc.__traceback__ is not None, "the premise: this exception carries a traceback"
    seam = _install_seam(monkeypatch, park_thread="producer")
    producer = _run_in_thread("producer", lambda: record_unexpected(("acct", "prof"), exc))
    assert seam.reached.wait(timeout=_TIMEOUT)
    seam.release.set()
    producer.join(timeout=_TIMEOUT)

    (record,) = take_unexpected()

    assert isinstance(record, UnexpectedRecord)
    assert [type(field) for field in tuple(record)] == [str, str, int], record

    seen: dict[int, object] = {}
    queue: list[object] = [record]
    while queue:
        item = queue.pop()
        if id(item) in seen or isinstance(item, type) or isinstance(item, ModuleType):
            continue
        seen[id(item)] = item
        assert not isinstance(item, BaseException), "the sink retained an exception"
        assert not isinstance(item, TracebackType), "the sink retained a traceback"
        assert not isinstance(item, FrameType), "the sink retained a frame"
        if isinstance(item, str):
            assert _SECRET not in item and _UPSTREAM not in item, item
        queue.extend(gc.get_referents(item))
    assert len(seen) <= 8, "the record graph must stay a handful of flat scalars"


def test_an_error_nobody_observed_still_fails_teardown() -> None:
    """The fix must not silence the sink: an UNobserved error is still a failure.

    Both channels are checked, because the dropped one is the severe case: reaching
    it means the failures arrived faster than the sink could describe them.
    """
    unobserved = AssertionError(_UPSTREAM)
    record_unexpected("never-observed", unobserved)

    with pytest.raises(AssertionError) as caught:
        assert_no_unexpected("last-mile teardown")

    message = str(caught.value)
    assert "never-observed" in message and "AssertionError" in message, message
    assert _UPSTREAM not in message and _SECRET not in message, message

    for index in range(_MAX_RETAINED_UNEXPECTED + 1):
        record_unexpected(f"burst{index}", AssertionError(_UPSTREAM))
    with pytest.raises(AssertionError) as overflowed:
        assert_no_unexpected("last-mile overflow")
    assert "dropped past the retention cap" in str(overflowed.value)
