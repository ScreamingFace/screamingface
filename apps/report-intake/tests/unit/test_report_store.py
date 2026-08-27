"""The `reports` table, through the only object allowed to write it.

Every test here runs against a database built by the committed `0001_initial` (see the
`database_url` fixture), so a column the models grew and the migration did not is a failure in
this file rather than a surprise on the first deploy.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from tortoise.exceptions import OperationalError

from report_intake.reports.models import Report
from report_intake.reports.pipeline import StorageUnavailable
from report_intake.reports.store import ReportStore, request_fingerprint

pytestmark = pytest.mark.asyncio

_TTL = timedelta(hours=24)
_RETENTION = timedelta(days=90)


def _store(clock: Any = None) -> ReportStore:
    if clock is None:
        return ReportStore(idempotency_ttl=_TTL, retention=_RETENTION)
    return ReportStore(idempotency_ttl=_TTL, retention=_RETENTION, clock=clock)


async def _record(store: ReportStore, **overrides: Any) -> Any:
    values: dict[str, Any] = {
        "payload": {"schema": "screamingface.error-report/v1", "note": "it broke"},
        "classification": "envelope",
        "caller_email": None,
        "reply_to": None,
        "idempotency_key": None,
    }
    values.update(overrides)
    return await store.record(**values)


async def test_a_recorded_report_is_committed_before_the_call_returns(storage: None) -> None:
    """Persist before deliver, spec §5. `record` returning means the row exists — there is no
    window in which a caller has a `ref` for something a crash could still lose."""
    recorded = await _record(_store())

    assert recorded.created is True
    assert await Report.filter(ref=recorded.report.ref).exists()


async def test_the_ref_is_server_minted_and_never_taken_from_the_caller(storage: None) -> None:
    """The primary key is the one column a client must not be able to influence, so the store
    mints it rather than accepting it — `record` has no parameter for it at all."""
    first = await _record(_store())
    second = await _record(_store())

    assert first.report.ref.startswith("r_")
    assert first.report.ref != second.report.ref


async def test_a_new_report_starts_pending_with_its_first_attempt_due_immediately(
    storage: None,
) -> None:
    """`next_attempt_at` and `lease_expires_at` are NOT NULL and default to the insert instant
    (plan §2.3): due now, held by nobody. A null in either is what `OME-1010`'s due-scan would
    read as "no attempt is owed"."""
    recorded = await _record(_store())

    row = await Report.get(ref=recorded.report.ref)
    assert row.delivery_state == "pending"
    assert row.attempts == 0
    assert row.next_attempt_at is not None
    assert row.lease_expires_at is not None
    assert row.ticket_id is None and row.ticket_url is None


async def test_the_stored_payload_is_the_report_and_the_verdict_is_the_servers(
    storage: None,
) -> None:
    recorded = await _record(_store(), payload={"note": "kept verbatim"}, classification="envelope")

    row = await Report.get(ref=recorded.report.ref)
    assert row.payload == {"note": "kept verbatim"}
    assert row.classification == "envelope"


async def test_a_replayed_key_inside_the_window_returns_the_original_record(
    storage: None,
) -> None:
    """Spec §5: one report, one ticket, regardless of double-clicks or client retries."""
    first = await _record(_store(), idempotency_key="key-42")
    second = await _record(_store(), idempotency_key="key-42")

    assert second.created is False
    assert second.report.ref == first.report.ref
    assert await Report.all().count() == 1


async def test_a_replay_returns_the_original_even_when_the_body_differs(storage: None) -> None:
    """The dedup key identifies the SUBMISSION, not its content (plan §6). The scoreboard keys
    on a content hash and `OME-970` is what that cost — a resubmission answered with another
    run's id."""
    first = await _record(_store(), payload={"note": "one"}, idempotency_key="key-42")
    second = await _record(_store(), payload={"note": "two"}, idempotency_key="key-42")

    assert second.report.ref == first.report.ref
    stored = await Report.get(ref=first.report.ref)
    assert stored.payload == {"note": "one"}


async def test_the_same_key_after_the_window_is_a_new_report(storage: None) -> None:
    """Spec §5: after 24 h the same key is treated as new. The old row survives — it is still
    owed its 90 days of retention, and it is the forensic record of what was filed."""
    opened = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    first = await _record(_store(clock=lambda: opened), idempotency_key="key-42")

    later = opened + _TTL + timedelta(minutes=1)
    second = await _record(_store(clock=lambda: later), idempotency_key="key-42")

    assert second.created is True
    assert second.report.ref != first.report.ref
    assert await Report.all().count() == 2


async def test_the_expired_binding_is_released_rather_than_the_row_deleted(storage: None) -> None:
    """`idempotency_key` is unique, so the stale binding would refuse the second insert. It is
    cleared from the old row instead of taking the row with it."""
    opened = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    first = await _record(_store(clock=lambda: opened), idempotency_key="key-42")
    later = opened + _TTL + timedelta(minutes=1)
    await _record(_store(clock=lambda: later), idempotency_key="key-42")

    assert (await Report.get(ref=first.report.ref)).idempotency_key is None


async def test_two_concurrent_submissions_of_one_key_produce_one_row(storage: None) -> None:
    """The `IntegrityError` race: both calls pass the lookup, one insert wins, and the loser
    replays the winner rather than failing a reporter's request."""
    store = _store()

    results = await asyncio.gather(
        _record(store, idempotency_key="key-42"),
        _record(store, idempotency_key="key-42"),
    )

    assert await Report.all().count() == 1
    assert {result.report.ref for result in results} == {results[0].report.ref}
    assert sorted(result.created for result in results) == [False, True]


async def test_a_report_without_a_key_is_never_deduplicated(storage: None) -> None:
    """Anonymous clients are not required to send one, and two reports that happen to look
    alike are two bugs until a client says otherwise."""
    await _record(_store(), payload={"note": "same"})
    await _record(_store(), payload={"note": "same"})

    assert await Report.all().count() == 2


async def test_the_fingerprint_is_written_but_never_resolves_a_replay(storage: None) -> None:
    """`request_fingerprint` is diagnostic. Two identical bodies get two rows above; here it is
    asserted that the column is nonetheless filled, because "did we already see this?" is a
    question a human reading the table should be able to answer."""
    payload = {"note": "same"}
    recorded = await _record(_store(), payload=payload)

    row = await Report.get(ref=recorded.report.ref)
    assert row.request_fingerprint == request_fingerprint(payload)


async def test_the_fingerprint_ignores_key_order(storage: None) -> None:
    """It is a digest of the report, not of the byte order a client's JSON serializer chose."""
    assert request_fingerprint({"a": 1, "b": 2}) == request_fingerprint({"b": 2, "a": 1})


async def test_a_storage_failure_raises_storage_unavailable_and_stores_nothing(
    storage: None,
) -> None:
    """Spec §2.3's `503` means NOTHING was stored, so the store's failure mode has to be all or
    nothing — a caller that gets this exception can tell its user to keep the report."""
    store = _store()
    await Report.raw("DROP TABLE reports")

    with pytest.raises(StorageUnavailable):
        await _record(store)


async def test_the_probe_is_true_against_a_migrated_database(storage: None) -> None:
    assert await _store().is_reachable() is True


async def test_the_probe_is_false_when_the_reports_table_is_gone(storage: None) -> None:
    """Fails closed on any ORM error rather than propagating: `/readyz` answers a kubelet, and a
    probe that raises is a 500 where a 503 belongs."""
    await Report.raw("DROP TABLE reports")

    assert await _store().is_reachable() is False


async def test_the_probe_does_not_swallow_an_error_it_was_never_meant_to_see() -> None:
    """The store is uninitialised here — no Tortoise, no connection — which is the shape of a
    pod whose database is simply not there. It still answers False rather than raising."""
    assert await _store().is_reachable() is False


async def test_purging_removes_rows_past_the_retention_window(storage: None) -> None:
    old = datetime(2026, 1, 1, tzinfo=UTC)
    recorded = await _record(_store())
    await Report.filter(ref=recorded.report.ref).update(created_at=old)

    purged = await _store().purge_expired(now=old + _RETENTION + timedelta(days=1))

    assert purged == 1
    assert await Report.all().count() == 0


async def test_purging_keeps_a_row_inside_the_retention_window(storage: None) -> None:
    """The row is what makes a replay, a retry, and a forensic answer possible; deleting one
    early costs all three."""
    await _record(_store())

    purged = await _store().purge_expired(now=datetime.now(UTC))

    assert purged == 0
    assert await Report.all().count() == 1


async def test_purging_a_missing_table_is_storage_unavailable_not_a_silent_zero(
    storage: None,
) -> None:
    """A purge that cannot run must be distinguishable from a purge that found nothing, or a
    retention policy quietly stops being enforced."""
    await Report.raw("DROP TABLE reports")

    with pytest.raises(StorageUnavailable):
        await _store().purge_expired()


async def test_a_storage_failure_keeps_the_original_error_attached(storage: None) -> None:
    """`raise ... from exc`: the ORM error is what an operator needs, and the `503` body
    deliberately says nothing about it."""
    await Report.raw("DROP TABLE reports")

    with pytest.raises(StorageUnavailable) as raised:
        await _record(_store())

    assert isinstance(raised.value.__cause__, OperationalError)


async def test_a_recorded_delivery_counts_the_attempt_and_leaves_the_retry_deadline_alone(
    storage: None,
) -> None:
    """`attempts` is `OME-1010`'s backoff input, so every attempt is counted — including one that
    got nowhere. `next_attempt_at` is not touched here: the retry schedule has one owner, and a
    row left due at `created_at` is exactly what that sweep is built to find."""
    recorded = await _record(_store())
    before = await Report.get(ref=recorded.report.ref)

    await _store().record_delivery(recorded.report.ref, state="pending")

    row = await Report.get(ref=recorded.report.ref)
    assert row.attempts == 1
    assert row.delivery_state == "pending"
    assert row.next_attempt_at == before.next_attempt_at


async def test_a_queued_report_is_terminal_and_carries_no_ticket(storage: None) -> None:
    """`queued` is a real state, never the absence of a timestamp (plan §2.3): `QueueSink`
    succeeding is terminal success, and a due-scan that read it as "no attempt scheduled" would
    retry every filed report six times and then alarm."""
    recorded = await _record(_store())

    persisted = await _store().record_delivery(recorded.report.ref, state="queued")

    assert persisted.delivery_state == "queued"
    assert (persisted.ticket_id, persisted.ticket_url) == (None, None)


async def test_a_filed_ticket_is_never_erased_by_a_later_outcome(storage: None) -> None:
    """The columns are the ticket's address. A second attempt coming back without one must not
    make a delivered report look undelivered."""
    recorded = await _record(_store())
    await _store().record_delivery(
        recorded.report.ref, state="delivered", ticket_id="OME-1042", ticket_url="https://x/1042"
    )

    await _store().record_delivery(recorded.report.ref, state="queued")

    row = await Report.get(ref=recorded.report.ref)
    assert (row.ticket_id, row.ticket_url) == ("OME-1042", "https://x/1042")


async def test_recording_a_delivery_never_rewrites_the_payload_or_moves_created_at(
    storage: None,
) -> None:
    """The two values every policy in this service measures against: the idempotency window and
    the retention cut-off both read `created_at`, and `payload` is the report itself."""
    recorded = await _record(_store(), payload={"note": "kept verbatim"})
    before = await Report.get(ref=recorded.report.ref)

    await _store().record_delivery(recorded.report.ref, state="queued")

    row = await Report.get(ref=recorded.report.ref)
    assert row.payload == {"note": "kept verbatim"}
    assert row.created_at == before.created_at


async def test_a_delivery_outcome_that_cannot_be_written_is_a_storage_failure(
    storage: None,
) -> None:
    """It is raised, not swallowed, because the store's contract is "committed or raised". The
    pipeline is what decides that a report already on disk must not be answered with a `503`."""
    recorded = await _record(_store())
    await Report.raw("DROP TABLE reports")

    with pytest.raises(StorageUnavailable):
        await _store().record_delivery(recorded.report.ref, state="queued")


# The retry claim (`OME-1010`). The property under every test below is that the DATABASE decides
# who owns a row, not the process that read it: two replicas sweep the same table at the same
# instant, and a report that reaches two sinks is a bug report filed twice.


async def _seed_due(age: timedelta = timedelta(minutes=5), **overrides: Any) -> str:
    """A `pending` row whose deadline and lease both fell `age` ago — the shape a failed inline
    attempt leaves behind."""
    at = datetime.now(UTC) - age
    recorded = await _record(_store(clock=lambda: at), **overrides)
    return recorded.report.ref


async def _claim(limit: int = 10, lease: timedelta = timedelta(minutes=5)) -> tuple[Any, ...]:
    now = datetime.now(UTC)
    return await _store().claim_due(due_before=now, lease_until=now + lease, limit=limit)


async def test_a_claim_takes_a_pending_report_whose_next_attempt_is_owed(storage: None) -> None:
    ref = await _seed_due()

    assert [due.ref for due in await _claim()] == [ref]


async def test_a_claim_leaves_a_report_whose_deadline_has_not_arrived(storage: None) -> None:
    """The backoff is only worth writing if the scan honours it."""
    ref = await _seed_due()
    await _store().record_delivery(
        ref, state="pending", next_attempt_at=datetime.now(UTC) + timedelta(hours=1)
    )

    assert await _claim() == ()


@pytest.mark.parametrize("state", ["queued", "delivered", "failed"])
async def test_a_claim_leaves_every_terminal_state_alone(storage: None, state: Any) -> None:
    """`pending` only (plan §2.3). `queued` is terminal SUCCESS — an agent files it from
    `queue list` — so a scan that read it as "no attempt scheduled" would re-deliver every filed
    report six times and then alarm on it."""
    ref = await _seed_due()
    await _store().record_delivery(ref, state=state)

    assert await _claim() == ()


async def test_a_claimed_report_is_not_offered_to_a_second_claim(storage: None) -> None:
    """The lease, which is the whole reason this service can run with `replicaCount > 1`. The
    second sweeper here is the second pod."""
    await _seed_due()

    first = await _claim()
    second = await _claim()

    assert len(first) == 1
    assert second == ()


async def test_a_report_whose_lease_expired_is_offered_again(storage: None) -> None:
    """A pod killed mid-attempt must not strand the report until the end of its backoff — which
    is what a claim recorded in one process's memory would do."""
    await _seed_due()
    await _claim(lease=timedelta(seconds=-1))

    assert len(await _claim()) == 1


async def test_a_claim_carries_the_payload_and_the_attempt_count_the_backoff_needs(
    storage: None,
) -> None:
    """`payload`, because a retry re-renders the report from the row rather than from a request
    that ended hours ago; `attempts`, because it is the backoff's only input."""
    ref = await _seed_due(payload={"note": "it broke"}, caller_email="engineer@openmined.org")
    await _store().record_delivery(ref, state="pending", next_attempt_at=datetime.now(UTC))

    due = (await _claim())[0]

    assert (due.ref, due.attempts) == (ref, 1)
    assert due.payload == {"note": "it broke"}
    assert due.caller_email == "engineer@openmined.org"


async def test_a_claim_takes_the_oldest_deadlines_first_and_no_more_than_the_limit(
    storage: None,
) -> None:
    """The batch is what stops a backlog from becoming one burst at the sink; the ordering is so
    that the reporter who has been waiting longest is served first."""
    oldest = await _seed_due(age=timedelta(hours=3))
    middle = await _seed_due(age=timedelta(hours=2))
    await _seed_due(age=timedelta(hours=1))

    assert [due.ref for due in await _claim(limit=2)] == [oldest, middle]


async def test_a_deadline_recorded_with_an_outcome_moves_the_schedule_and_frees_the_lease(
    storage: None,
) -> None:
    """One statement, not two: a crash between recording the outcome and recording the schedule
    would leave a row whose attempt was counted and whose next attempt was not booked. The lease
    is released to the same moment, so the row becomes claimable exactly when it falls due."""
    ref = await _seed_due()
    when = datetime.now(UTC) + timedelta(minutes=12)

    await _store().record_delivery(ref, state="pending", next_attempt_at=when)

    row = await Report.get(ref=ref)
    assert row.next_attempt_at == when
    assert row.lease_expires_at == when


async def test_claiming_from_a_missing_table_is_storage_unavailable(storage: None) -> None:
    """A sweep that cannot claim is a sweep that does nothing. The store still raises, because
    its contract is "committed or raised" and the retry loop is what decides to keep going."""
    await Report.raw("DROP TABLE reports")

    with pytest.raises(StorageUnavailable):
        await _claim()
