"""`StorePipeline` — the seam `create_app` installs: bounded report in, committed row out, ticket
attempted.

The order of those last two is spec §5's persist-before-deliver rule, and the tests that assert it
do so from inside the sink: the sink itself queries the table it is being called about.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from report_intake.config import Settings
from report_intake.delivery.dispatch import TicketDispatcher
from report_intake.delivery.ports import (
    Delivered,
    Queued,
    RetryableDeliveryError,
    SinkResult,
    TicketContent,
)
from report_intake.delivery.queue_sink import QueueSink
from report_intake.main import create_app
from report_intake.reports.binding import bind
from report_intake.reports.caps import NOTE_BYTES
from report_intake.reports.models import Report
from report_intake.reports.pipeline import BindOnlyPipeline, StorageUnavailable, Submission
from report_intake.reports.store import PersistedReport, ReportStore
from report_intake.reports.store_pipeline import StorePipeline

from .test_report_schema import a_report, as_body

pytestmark = pytest.mark.asyncio


class _RowReadingSink:
    """A sink that answers the question this seam exists to settle: was the row already there?"""

    def __init__(self, result: SinkResult | BaseException = Queued()) -> None:
        self._result = result
        self.rows_seen: list[bool] = []

    async def deliver(self, content: TicketContent) -> SinkResult:
        self.rows_seen.append(await Report.filter(ref=content.ref).exists())
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


def _store() -> ReportStore:
    return ReportStore(idempotency_ttl=timedelta(hours=24), retention=timedelta(days=90))


def _pipeline(sink: Any = None, timeout: float = 3.0) -> StorePipeline:
    return StorePipeline(_store(), TicketDispatcher(sink or QueueSink(), timeout=timeout))


def _submission(dedup_key: str | None = None, **overrides: Any) -> Submission:
    return Submission(
        bound=bind(as_body(a_report(**overrides))),
        classification="envelope",
        dedup_key=dedup_key,
        caller_email=None,
    )


async def test_a_submitted_report_is_queued_by_the_sink_this_deployment_runs(
    storage: None,
) -> None:
    """v1's sink is `QueueSink`: the row is marked ready for an agent to file via MCP during
    triage, and no ticket id comes back — which is spec §2.2's success shape, not a shortfall."""
    accepted = await _pipeline().submit(_submission())

    assert accepted.delivery_state == "queued"
    assert accepted.ticket is None
    assert accepted.replayed is False


async def test_the_row_exists_by_the_time_the_pipeline_answers(storage: None) -> None:
    """Persist before deliver, asserted at the seam a sink will later be added to: the commit
    is upstream of anything that could fail to file the ticket."""
    accepted = await _pipeline().submit(_submission())

    assert await Report.filter(ref=accepted.ref).exists()


async def test_a_replay_answers_with_the_original_record_marked_replayed(storage: None) -> None:
    """`replayed` is what makes the route answer `200` instead of `202`, and the `ref` is the
    original one — the client gets back the report it already filed, not a second one."""
    first = await _pipeline().submit(_submission(dedup_key="key-42"))
    second = await _pipeline().submit(_submission(dedup_key="key-42"))

    assert second.replayed is True
    assert second.ref == first.ref


async def test_the_persisted_payload_is_the_truncated_one_not_the_scanned_one(
    storage: None,
) -> None:
    """`BoundedReport` carries both, and only one of them is storage. `scanned` is
    pre-truncation and exists solely so the classifier cannot be walked around by pushing text
    past a field cap (plan §2.7); persisting it would put back every byte §2.4 says to cut.
    """
    submission = _submission(note="n" * (NOTE_BYTES * 2))

    accepted = await _pipeline().submit(submission)

    stored = (await Report.get(ref=accepted.ref)).payload
    assert stored["note"] == submission.bound.payload["note"]
    assert stored["note"] != submission.bound.scanned["note"]


async def test_the_reply_to_address_is_persisted_and_is_not_identity(storage: None) -> None:
    """It is how a responder answers an SDK report at all — the Python client parses only `exp`
    from its Access token, so it has no email of its own. It lands in its own column, not in
    `caller_email`, because nothing authorizes on it."""
    accepted = await _pipeline().submit(_submission(reply_to="reporter@example.org"))

    row = await Report.get(ref=accepted.ref)
    assert row.reply_to == "reporter@example.org"
    assert row.caller_email is None


async def test_the_mesh_caller_email_is_persisted_when_the_submission_carries_one(
    storage: None,
) -> None:
    """`OME-1011` fills `Submission.caller_email` after the peer check; the column it lands in
    is wired now so that item adds an adapter rather than a migration."""
    submission = Submission(
        bound=bind(as_body(a_report())),
        classification="envelope",
        dedup_key=None,
        caller_email="engineer@openmined.org",
    )

    accepted = await _pipeline().submit(submission)

    assert (await Report.get(ref=accepted.ref)).caller_email == "engineer@openmined.org"


async def test_the_verdict_persisted_is_the_one_the_route_decided(storage: None) -> None:
    """The pipeline does not classify. Spec §4 rejects content rather than storing it, and the
    only structural guarantee of that is that the refusal happened before this object was
    reached — so the verdict travels in, it is not re-invented here."""
    accepted = await _pipeline().submit(_submission())

    assert (await Report.get(ref=accepted.ref)).classification == "envelope"
    assert accepted.classification == "envelope"


async def test_create_app_installs_the_store_pipeline_on_the_seam(
    hermetic_environment: None, database_url: str
) -> None:
    """Plan §6: the whole item lands as one assignment at the composition root. A route that had
    to know about storage is the alternative."""
    app = create_app(Settings(database_url=database_url))

    assert isinstance(app.state.report_pipeline, StorePipeline)


async def test_the_null_pipeline_still_satisfies_the_port_and_is_not_what_gets_installed() -> None:
    """`BindOnlyPipeline` survives as the port's null implementation for tests that are about
    routing rather than storage. It stores nothing, so a `create_app` that reached for it as a
    fallback would answer `202` for reports that do not exist — which is precisely what spec
    §2.3's `503` exists to make visible."""
    accepted = await BindOnlyPipeline().submit(_submission())

    assert accepted.delivery_state == "pending"
    assert accepted.replayed is False


async def test_the_row_exists_by_the_time_the_sink_is_called(storage: None) -> None:
    """Persist before deliver, asserted from inside the sink rather than around it. Calling the
    sink first and storing on success is the single most common way a service like this drops
    reports, and spec §5 prohibits it."""
    sink = _RowReadingSink()

    await _pipeline(sink).submit(_submission())

    assert sink.rows_seen == [True]


async def test_a_replay_files_no_second_ticket(storage: None) -> None:
    """One report, one ticket, regardless of double-clicks or client retries (spec §5). Delivering
    on a replay would make the idempotency window a way to file the same bug twice."""
    sink = _RowReadingSink()
    pipeline = _pipeline(sink)

    first = await pipeline.submit(_submission(dedup_key="key-42"))
    second = await pipeline.submit(_submission(dedup_key="key-42"))

    assert len(sink.rows_seen) == 1
    assert (second.ref, second.replayed) == (first.ref, True)
    assert second.delivery_state == "queued"


async def test_a_sink_outage_leaves_a_durable_report_pending_rather_than_failing_it(
    storage: None,
) -> None:
    """Plan §13's cross-item case. The reporter is not the one who should find out that our
    tracker is down."""
    accepted = await _pipeline(_RowReadingSink(RetryableDeliveryError("502"))).submit(_submission())

    assert accepted.delivery_state == "pending"
    assert await Report.filter(ref=accepted.ref).exists()


async def test_a_sink_that_hangs_does_not_hold_the_reporter_past_the_deadline(
    storage: None,
) -> None:
    """Spec §6's inline timeout, compressed. Past it the row stays `pending` and the response is
    still `202` — raising the deadline would not make delivery more likely, only filing slower."""

    class _HangingSink:
        async def deliver(self, content: TicketContent) -> SinkResult:
            await asyncio.sleep(30)
            return Queued()

    accepted = await _pipeline(_HangingSink(), timeout=0.01).submit(_submission())

    assert accepted.delivery_state == "pending"


async def test_a_delivered_report_answers_with_the_ticket_the_sink_returned(
    storage: None,
) -> None:
    """The `LinearSink` shape, exercised through the port today so the row and the response are
    already wired for it."""
    sink = _RowReadingSink(Delivered(ticket_id="OME-1042", ticket_url="https://linear.app/x"))

    accepted = await _pipeline(sink).submit(_submission())

    assert accepted.delivery_state == "delivered"
    assert accepted.ticket is not None
    assert (accepted.ticket.id, accepted.ticket.url) == ("OME-1042", "https://linear.app/x")
    row = await Report.get(ref=accepted.ref)
    assert (row.ticket_id, row.ticket_url) == ("OME-1042", "https://linear.app/x")


async def test_the_inline_attempt_is_counted_even_though_the_retry_deadline_is_not_moved(
    storage: None,
) -> None:
    """`attempts` is what `OME-1010`'s backoff counts, so a row claiming zero attempts after the
    inline one has run understates how hard this report has already been tried. `next_attempt_at`
    is left where the insert put it — the retry schedule has exactly one owner, and it is not
    this item."""
    accepted = await _pipeline().submit(_submission())

    row = await Report.get(ref=accepted.ref)
    assert row.attempts == 1
    assert row.next_attempt_at == row.created_at


async def test_an_outcome_that_cannot_be_recorded_does_not_fail_a_durable_report(
    storage: None,
) -> None:
    """The report is committed by the time the outcome is written, so a `503` here would tell a
    client with a durable report that nothing was stored — and it would file the same report
    again. A duplicate ticket is visible and cheap; a lost bug report is neither."""

    class _UnrecordableOutcomeStore(ReportStore):
        async def record_delivery(self, ref: str, **_: Any) -> PersistedReport:
            raise StorageUnavailable("the database went away between the two writes")

    pipeline = StorePipeline(
        _UnrecordableOutcomeStore(
            idempotency_ttl=timedelta(hours=24), retention=timedelta(days=90)
        ),
        TicketDispatcher(QueueSink(), timeout=3.0),
    )

    accepted = await pipeline.submit(_submission())

    assert accepted.delivery_state == "pending"
    assert await Report.filter(ref=accepted.ref).exists()
