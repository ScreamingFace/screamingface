"""Spec §6's retry queue: what a `pending` report gets, and what it never gets twice.

The wiring half matters as much as the policy half, and it is quieter here than anywhere else in
this service: nothing in a response tells a reporter whether their `pending` report was ever
tried again, so a loop that never ran would look exactly like a sink that never came back. The
last tests in this file assert through the deployed wiring for that reason.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from report_intake.config import Settings
from report_intake.db import close_db, init_db
from report_intake.delivery.dispatch import TicketDispatcher
from report_intake.delivery.ports import (
    Delivered,
    PermanentDeliveryError,
    Queued,
    RetryableDeliveryError,
    SinkResult,
    TicketContent,
)
from report_intake.delivery.queue_sink import QueueSink
from report_intake.delivery.render import render_ticket
from report_intake.main import create_app
from report_intake.reports.binding import bind
from report_intake.reports.models import Report
from report_intake.reports.pipeline import DeliveryState, StorageUnavailable
from report_intake.reports.retry import (
    BATCH_LIMIT,
    CLAIM_GRACE,
    MAX_ATTEMPTS,
    RETRY_BACKOFF,
    SWEEP_INTERVAL,
    RetryQueue,
)
from report_intake.reports.store import STORAGE_TIMEOUT_S, ReportStore

from .test_report_schema import a_report, as_body

_OLD = timedelta(minutes=5)
"""Older than `CLAIM_GRACE`, so a seeded row is one the sweep is allowed to touch."""


class _RecordingSink:
    """Answers whatever it was built with, and remembers everything it was handed."""

    def __init__(self, result: SinkResult | BaseException = Queued()) -> None:
        self._result = result
        self.received: list[TicketContent] = []

    async def deliver(self, content: TicketContent) -> SinkResult:
        self.received.append(content)
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


class _OneAtATimeSink:
    """Watches how many reports the sweep has in flight at once."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.peak = 0
        self.received: list[TicketContent] = []

    async def deliver(self, content: TicketContent) -> SinkResult:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        self.received.append(content)
        return Queued()


class _Captured(logging.Handler):
    """The log lines this module emitted, collected from its own logger.

    Not `caplog`, which installs its handler on the ROOT logger: `logs.configure` sets
    `propagate = False` across the `report_intake` tree on purpose (so a later root
    configuration cannot double every record), and any test in this session that builds an app
    has already called it. A root handler would therefore see nothing, and the assertions below
    would pass for the wrong reason and then fail for a worse one.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def text(self) -> str:
        return "\n".join(record.getMessage() for record in self.records)


@contextmanager
def _capturing(level: int = logging.ERROR) -> Iterator[_Captured]:
    logger = logging.getLogger("report_intake.reports.retry")
    handler = _Captured()
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(level)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


class _RefusingStore:
    async def claim_due(self, **_: Any) -> tuple[Any, ...]:
        raise StorageUnavailable("the database is gone")


class _CountingStore(_RefusingStore):
    def __init__(self) -> None:
        self.sweeps = 0

    async def claim_due(self, **_: Any) -> tuple[Any, ...]:
        self.sweeps += 1
        return ()


def _store(clock: Any = None) -> ReportStore:
    if clock is None:
        return ReportStore(idempotency_ttl=timedelta(hours=24), retention=timedelta(days=90))
    return ReportStore(
        idempotency_ttl=timedelta(hours=24), retention=timedelta(days=90), clock=clock
    )


def _queue(sink: Any = None, clock: Any = None, **overrides: Any) -> RetryQueue:
    return RetryQueue(
        _store(),
        TicketDispatcher(sink if sink is not None else QueueSink(), timeout=3.0),
        clock=clock if clock is not None else lambda: datetime.now(UTC),
        **overrides,
    )


async def _seed(
    *,
    age: timedelta = _OLD,
    attempts: int = 0,
    state: DeliveryState = "pending",
    payload: Mapping[str, Any] | None = None,
    caller_email: str | None = None,
) -> str:
    """A row in the state a failed attempt leaves behind: `pending`, due `age` ago, unleased.

    `attempts` is walked up through `record_delivery`, the only writer of that column, so the row
    is one the service could really have produced rather than one only a test can build.
    """
    at = datetime.now(UTC) - age
    recorded = await _store(clock=lambda: at).record(
        payload=payload if payload is not None else bind(as_body(a_report())).payload,
        classification="envelope",
        caller_email=caller_email,
        reply_to=None,
        idempotency_key=None,
    )
    ref = recorded.report.ref
    for _ in range(attempts):
        await _store().record_delivery(ref, state="pending", next_attempt_at=at)
    if state != "pending":
        await _store().record_delivery(ref, state=state, next_attempt_at=at)
    return ref


@pytest.mark.asyncio
async def test_a_pending_report_past_its_deadline_is_delivered_on_the_next_sweep(
    storage: None,
) -> None:
    """The point of the whole item: `pending` stops meaning "and nothing will ever happen"."""
    ref = await _seed()
    sink = _RecordingSink()

    assert await _queue(sink).sweep() == 1

    assert [content.ref for content in sink.received] == [ref]
    assert (await Report.get(ref=ref)).delivery_state == "queued"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["queued", "delivered", "failed"])
async def test_a_report_in_a_terminal_state_is_never_swept(
    storage: None, state: DeliveryState
) -> None:
    """`queued` is terminal SUCCESS (plan §2.3, §11 conflict 8): the row is in `queue list` for an
    agent to file. A sweep that read it as "no attempt is scheduled" would re-deliver every filed
    report six times and then alarm on it as permanently failed."""
    await _seed(state=state)
    sink = _RecordingSink()

    assert await _queue(sink).sweep() == 0
    assert sink.received == []


@pytest.mark.asyncio
async def test_a_report_whose_backoff_has_not_elapsed_is_left_alone(storage: None) -> None:
    """Writing a deadline is only worth doing if the scan honours it."""
    ref = await _seed()
    await _store().record_delivery(
        ref, state="pending", next_attempt_at=datetime.now(UTC) + timedelta(hours=1)
    )
    sink = _RecordingSink()

    assert await _queue(sink).sweep() == 0
    assert sink.received == []


@pytest.mark.asyncio
async def test_a_report_the_request_path_may_still_be_delivering_is_left_alone(
    storage: None,
) -> None:
    """The inline attempt holds NO lease: the row is committed `pending`, due at `created_at` and
    unleased, and only then is the sink called. Without the grace a sweeper on another replica
    would claim a report the request path is already filing, and one bug report would become two
    tickets through the one door the lease does not cover."""
    await _seed(age=timedelta(seconds=1))
    sink = _RecordingSink()

    assert await _queue(sink).sweep() == 0
    assert sink.received == []


def test_the_grace_outlasts_the_worst_case_inline_attempt() -> None:
    """Not a round number chosen by feel: it has to cover a whole inline attempt — the commit,
    the sink deadline, and the write that records the outcome — or the case above reopens. If
    `delivery_timeout_s` is ever raised past this, the grace moves with it."""
    inline_worst_case = timedelta(
        seconds=Settings().delivery_timeout_s + STORAGE_TIMEOUT_S + STORAGE_TIMEOUT_S
    )

    assert CLAIM_GRACE > inline_worst_case


@pytest.mark.asyncio
async def test_each_attempt_books_the_next_step_of_the_backoff(storage: None) -> None:
    """Spec §6's exponential backoff, read off the row rather than out of a comment. The step is
    chosen by how many attempts the report has had, which is why `attempts` counts them all."""
    ref = await _seed(attempts=2)
    moment = datetime.now(UTC)

    await _queue(_RecordingSink(RetryableDeliveryError("502")), clock=lambda: moment).sweep()

    row = await Report.get(ref=ref)
    assert row.attempts == 3
    assert row.next_attempt_at == moment + RETRY_BACKOFF[2]


@pytest.mark.asyncio
async def test_a_retry_that_gets_nowhere_stays_pending_and_keeps_its_place_in_the_queue(
    storage: None,
) -> None:
    """`RetryableDeliveryError` is the half of the taxonomy that means "not now"; the row has to
    come back to this sweep, and unleased, or it waits five minutes for nothing."""
    ref = await _seed()

    await _queue(_RecordingSink(RetryableDeliveryError("502"))).sweep()

    row = await Report.get(ref=ref)
    assert row.delivery_state == "pending"
    assert row.lease_expires_at == row.next_attempt_at


@pytest.mark.asyncio
async def test_a_permanent_refusal_ends_the_report_without_spending_the_budget(
    storage: None,
) -> None:
    """The other half of the taxonomy: a body the tracker will never accept does not become six
    identical calls over 24 h."""
    ref = await _seed()

    await _queue(_RecordingSink(PermanentDeliveryError("rejected"))).sweep()

    assert (await Report.get(ref=ref)).delivery_state == "failed"


@pytest.mark.asyncio
async def test_a_delivered_retry_records_the_ticket_the_sink_returned(storage: None) -> None:
    """The `LinearSink` shape, through the retry path — the row a reporter's `ref` resolves to is
    the one that has to carry the ticket, whichever attempt finally filed it."""
    ref = await _seed()
    sink = _RecordingSink(Delivered(ticket_id="OME-1042", ticket_url="https://linear.app/x"))

    await _queue(sink).sweep()

    row = await Report.get(ref=ref)
    assert row.delivery_state == "delivered"
    assert (row.ticket_id, row.ticket_url) == ("OME-1042", "https://linear.app/x")


@pytest.mark.asyncio
async def test_the_last_attempt_that_gets_nowhere_is_terminal_and_says_so(storage: None) -> None:
    """Spec §6: a report we permanently failed to file is an operational event, not a shrug. The
    log line is what an alert is built on, and the row is still readable behind Access."""
    ref = await _seed(attempts=MAX_ATTEMPTS - 1)

    with _capturing() as logs:
        await _queue(_RecordingSink(RetryableDeliveryError("502"))).sweep()

    row = await Report.get(ref=ref)
    assert (row.delivery_state, row.attempts) == ("failed", MAX_ATTEMPTS)
    assert ref in logs.text
    assert "terminally" in logs.text


@pytest.mark.asyncio
async def test_a_terminally_failed_report_is_never_swept_again(storage: None) -> None:
    """Terminal means terminal. A seventh attempt would be a report nobody is waiting on eating
    a rate limit somebody else's report needs."""
    await _seed(attempts=MAX_ATTEMPTS - 1)
    queue = _queue(_RecordingSink(RetryableDeliveryError("502")))

    await queue.sweep()

    assert await queue.sweep() == 0


def test_the_schedule_is_six_attempts_across_twenty_four_hours() -> None:
    """Plan §8's arithmetic, asserted rather than asserted-in-a-comment:
    `720 + 2160 + 6480 + 19440 + 57600 = 86400`. Six attempts have five gaps between them, which
    is why the budget is derived from the schedule instead of written down twice."""
    assert sum(RETRY_BACKOFF, timedelta()) == timedelta(hours=24)
    assert MAX_ATTEMPTS == 6
    assert [step.total_seconds() for step in RETRY_BACKOFF] == [720, 2160, 6480, 19440, 57600]


@pytest.mark.asyncio
async def test_two_replicas_sweeping_at_the_same_instant_file_one_report_once(
    storage: None,
) -> None:
    """The reason the claim is a conditional UPDATE and not a read-then-write. Two pods is the
    ordinary deployment, and a bug report filed twice is two triage conversations."""
    await _seed()
    sink = _RecordingSink()

    await asyncio.gather(_queue(sink).sweep(), _queue(sink).sweep())

    assert len(sink.received) == 1


@pytest.mark.asyncio
async def test_a_sweep_attempts_one_batch_at_most(storage: None) -> None:
    """The batch per interval is the ceiling on how fast this service can talk to a sink — spec
    §6's "retries must not stampede". The backoff cannot do it: an outage fails every row in the
    same sweep, which books all of their next attempts into the same instant."""
    for _ in range(3):
        await _seed()
    sink = _RecordingSink()

    assert await _queue(sink, batch=2).sweep() == 2
    assert len(sink.received) == 2


@pytest.mark.asyncio
async def test_the_sink_is_never_handed_two_reports_at_once(storage: None) -> None:
    """The other half of not stampeding: the batch bounds how many an interval may attempt, and
    attempting them in turn bounds how many arrive together."""
    for _ in range(3):
        await _seed()
    sink = _OneAtATimeSink()

    await _queue(sink).sweep()

    assert len(sink.received) == 3
    assert sink.peak == 1


@pytest.mark.asyncio
async def test_a_sweep_that_cannot_reach_the_database_does_not_raise() -> None:
    """An exception escaping `sweep` ends the loop for the life of the process — and silently,
    because nothing in a response mentions retry. The database being briefly unreachable is what
    `/readyz` is for."""
    queue = RetryQueue(_RefusingStore(), TicketDispatcher(QueueSink(), timeout=3.0))  # type: ignore[arg-type]

    assert await queue.sweep() == 0


@pytest.mark.asyncio
async def test_a_stored_payload_that_no_longer_validates_is_failed_rather_than_raised(
    storage: None,
) -> None:
    """A row survives 90 days and this schema will change. A payload written against an older
    shape cannot be rendered, so it is terminal rather than retryable — five more attempts would
    re-validate the same bytes — and it must not be an exception in the middle of a sweep that
    has other reports to file."""
    ref = await _seed(payload={"schema": "screamingface.error-report/v1"})
    sink = _RecordingSink()

    with _capturing() as logs:
        assert await _queue(sink).sweep() == 1

    assert sink.received == []
    assert (await Report.get(ref=ref)).delivery_state == "failed"
    assert "occurred_at" in logs.text


@pytest.mark.asyncio
async def test_a_refusal_log_never_quotes_the_payload_it_could_not_read(storage: None) -> None:
    """`binding.py`'s rule, which does not stop applying because this is a log rather than a
    response: pydantic's error objects carry the offending VALUE, so the locations are read by
    name and the exception is never serialized whole."""
    ref = await _seed(payload={"note": "a prompt a reporter pasted by accident"})

    with _capturing() as logs:
        await _queue().sweep()

    assert ref in logs.text
    assert "a prompt a reporter pasted by accident" not in logs.text


@pytest.mark.asyncio
async def test_a_retried_ticket_is_the_body_the_inline_attempt_would_have_sent(
    storage: None,
) -> None:
    """`render_ticket` takes a document rather than a `BoundedReport` precisely so that a report
    re-read from its row renders identically. A retry that produced a subtly different body would
    be sending something nobody reviewed."""
    bound = bind(as_body(a_report(note="the engine hung")))
    ref = await _seed(payload=bound.payload)
    sink = _RecordingSink()

    await _queue(sink).sweep()

    expected = render_ticket(ref=ref, document=bound.document, caller_email=None)
    assert sink.received[0].body == expected.body
    assert sink.received[0].title == expected.title


@pytest.mark.asyncio
async def test_a_retry_carries_the_mesh_verified_caller_the_row_recorded(storage: None) -> None:
    """The identity was verified once, at the request that stored the report. A retry hours later
    has no peer to check, which is why the column is what it reads — and why it is a column."""
    ref = await _seed(caller_email="engineer@openmined.org")
    sink = _RecordingSink()

    await _queue(sink).sweep()

    assert sink.received[0].caller_email == "engineer@openmined.org"
    assert ref == sink.received[0].ref


@pytest.mark.asyncio
async def test_an_outcome_that_cannot_be_recorded_keeps_the_lease_rather_than_losing_the_report(
    storage: None,
) -> None:
    """The row is claimed and its lease is the only thing holding it. Letting the failure out
    would end the sweep; swallowing it without a lease would drop the report. It comes back when
    the lease expires, at the cost of one duplicate attempt — the same trade the inline path
    documents."""

    class _UnrecordableOutcomeStore(ReportStore):
        async def record_delivery(self, ref: str, **_: Any) -> Any:
            raise StorageUnavailable("the database went away mid-sweep")

    ref = await _seed()
    queue = RetryQueue(
        _UnrecordableOutcomeStore(
            idempotency_ttl=timedelta(hours=24), retention=timedelta(days=90)
        ),
        TicketDispatcher(QueueSink(), timeout=3.0),
    )

    assert await queue.sweep() == 1

    row = await Report.get(ref=ref)
    assert (row.delivery_state, row.attempts) == ("pending", 0)
    assert row.lease_expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_the_loop_sweeps_before_it_waits() -> None:
    """A pod restarted more often than the interval — the ordinary life of a pod during a
    rollout — would otherwise never retry anything at all."""
    store = _CountingStore()
    queue = RetryQueue(
        store,  # type: ignore[arg-type]
        TicketDispatcher(QueueSink(), timeout=3.0),
        interval=timedelta(days=1),
    )

    task = asyncio.create_task(queue.run())
    await asyncio.sleep(0)
    task.cancel()

    assert store.sweeps == 1


@pytest.mark.asyncio
async def test_the_loop_stops_when_it_is_cancelled() -> None:
    """Shutdown has to end it, or the lifespan's `finally` waits a minute on a sleeping task."""
    queue = RetryQueue(
        _CountingStore(),  # type: ignore[arg-type]
        TicketDispatcher(QueueSink(), timeout=3.0),
        interval=timedelta(days=1),
    )
    task = asyncio.create_task(queue.run())
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_the_interval_and_the_batch_bound_how_hard_a_backlog_can_hit_a_sink() -> None:
    """Twenty attempts a minute, whatever the backlog. Named here so a change to either is a
    change to a test rather than a silent edit to a constant nobody reads."""
    assert (SWEEP_INTERVAL, BATCH_LIMIT) == (timedelta(seconds=60), 20)


def test_the_retry_loop_runs_from_the_lifespan_rather_than_a_dropped_startup_handler(
    hermetic_environment: None, database_url: str
) -> None:
    """Plan §11 conflict 12, asserted through the deployed wiring: a due report seeded before
    startup is delivered shortly after the app is serving. A loop registered on
    `app.router.on_startup` would leave it `pending` forever while every other test here passed —
    and nothing in any response would say so.
    """
    ref = asyncio.run(_seed_in(database_url))
    assert _state(database_url, ref) == "pending"

    with TestClient(create_app(Settings(database_url=database_url))) as client:
        assert client.get("/healthz").status_code == 200
        assert _eventually(database_url, ref, "queued"), "the retry loop never ran"


def test_the_lifespan_owns_the_retry_task_and_ends_it_on_shutdown(
    hermetic_environment: None, database_url: str
) -> None:
    """Owned, because the event loop keeps only a weak reference to a bare `create_task` and a
    task nobody holds can be collected mid-sweep."""
    app = create_app(Settings(database_url=database_url))

    with TestClient(app):
        task = app.state.retry_queue
        assert not task.done()

    assert task.cancelled()


def test_the_request_path_delivers_through_the_dispatcher_on_app_state(
    hermetic_environment: None, database_url: str
) -> None:
    """A retry that built its own would be a second delivery path — a second renderer, a second
    fail-closed re-check, a second deadline — and the body a sink receives on the sixth attempt
    would be nobody's reviewed output.

    Identity, not `isinstance`: a `StorePipeline` handed a dispatcher built beside the shared one
    passes every type check and is exactly the regression this asserts against.
    """
    app = create_app(Settings(database_url=database_url))

    assert app.state.report_pipeline._dispatcher is app.state.ticket_dispatcher


def test_the_retry_loop_is_handed_the_dispatcher_on_app_state(
    hermetic_environment: None, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half, and the one nothing else can see: `_lifespan` constructs the queue and keeps
    only the TASK, so what the queue was handed leaves no trace on `app.state` to assert against.
    Recording the construction is the only way to catch a second dispatcher — with its own deadline
    — being built for the retry path.
    """
    handed: list[TicketDispatcher] = []

    class _RecordingRetryQueue(RetryQueue):
        def __init__(self, store: Any, dispatcher: TicketDispatcher, **kwargs: Any) -> None:
            handed.append(dispatcher)
            super().__init__(store, dispatcher, **kwargs)

    monkeypatch.setattr("report_intake.main.RetryQueue", _RecordingRetryQueue)
    app = create_app(Settings(database_url=database_url))

    with TestClient(app):
        assert handed == [app.state.ticket_dispatcher]


async def _seed_in(database_url: str) -> str:
    await init_db(database_url)
    try:
        return await _seed()
    finally:
        await close_db()


def _state(database_url: str, ref: str) -> str | None:
    connection = sqlite3.connect(database_url.removeprefix("sqlite://"))
    try:
        rows = connection.execute("SELECT delivery_state FROM reports WHERE ref = ?", (ref,))
        return next((row[0] for row in rows), None)
    finally:
        connection.close()


def _eventually(database_url: str, ref: str, state: str, timeout_s: float = 5.0) -> bool:
    """Poll rather than sleep once: the sweep runs on the app's own loop in another thread, so the
    only honest assertion is "this happens", not "this has already happened"."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _state(database_url, ref) == state:
            return True
        time.sleep(0.01)
    return False
