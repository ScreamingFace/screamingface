"""`POST /v1/reports` with a real store behind it — spec §2.2's two statuses and §2.3's `503`.

The row assertions read the database with `sqlite3` rather than through the ORM, deliberately.
The app under test holds Tortoise's global state on its own loop, and the point of "the table is
empty" is that it is checked from OUTSIDE the machinery that was supposed to have written it.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi.testclient import TestClient

from report_intake.core.problem import PROBLEM_MEDIA_TYPE
from report_intake.delivery.dispatch import TicketDispatcher
from report_intake.delivery.queue_sink import QueueSink
from report_intake.identity.mesh_identity import MESH_IDENTITY_HEADER
from report_intake.reports.models import EMAIL_MAX_LENGTH
from report_intake.reports.pipeline import StorageUnavailable
from report_intake.reports.store import Recorded
from report_intake.reports.store_pipeline import StorePipeline

from .test_report_schema import a_report


def _post(client: TestClient, document: Any, **headers: str) -> Any:
    return client.post(
        "/v1/reports",
        content=json.dumps(document).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
    )


def _mesh(email: str, key: str) -> dict[str, str]:
    """A mesh-verified caller with a replay key. Two callers on one deployment are two addresses
    behind ONE peer — the mesh proxy is the peer on every request — which is exactly why the
    dedup scope cannot be the peer for this caller class."""
    return {MESH_IDENTITY_HEADER: email, "Idempotency-Key": key}


def _rows(database_url: str) -> list[sqlite3.Row]:
    connection = sqlite3.connect(database_url.removeprefix("sqlite://"))
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute("SELECT * FROM reports").fetchall()
    finally:
        connection.close()


class _UnavailableStore:
    """A store that cannot commit. Plan §6 names this exact test: with the store raising, the
    `POST` answers `503` and the table stays empty."""

    async def record(self, **_: Any) -> Recorded:
        raise StorageUnavailable("the database is gone")


def _unavailable_pipeline() -> StorePipeline:
    """The store is what fails here; the sink is real and is never reached, which is the point —
    persist-before-deliver means a storage failure happens upstream of delivery."""
    return StorePipeline(
        _UnavailableStore(),  # type: ignore[arg-type]
        TicketDispatcher(QueueSink(), timeout=3.0),
    )


def test_an_accepted_report_is_on_disk_before_the_202_is_written(
    client: TestClient, database_url: str
) -> None:
    response = _post(client, a_report(note="the websocket closed mid-run"))

    assert response.status_code == 202
    rows = _rows(database_url)
    assert [row["ref"] for row in rows] == [response.json()["ref"]]
    # Committed first, then delivered: `queued` is what the inline `QueueSink` attempt left
    # behind, and it is read here from outside the machinery that wrote it.
    assert rows[0]["delivery_state"] == "queued"
    assert rows[0]["attempts"] == 1


def test_the_stored_payload_is_the_report_the_client_sent(
    client: TestClient, database_url: str
) -> None:
    document = a_report(note="it broke on the third question")

    _post(client, document)

    stored = json.loads(_rows(database_url)[0]["payload"])
    assert stored["note"] == "it broke on the third question"
    assert stored["error"]["message"] == document["error"]["message"]


def test_a_replayed_idempotency_key_answers_200_with_the_original_ref(
    client: TestClient, database_url: str
) -> None:
    """Spec §5: one report, one ticket, regardless of double-clicks or client retries. The two
    statuses are the only thing that distinguishes the shapes."""
    first = _post(client, a_report(), **{"Idempotency-Key": "key-42"})
    second = _post(client, a_report(), **{"Idempotency-Key": "key-42"})

    assert (first.status_code, second.status_code) == (202, 200)
    assert second.json()["ref"] == first.json()["ref"]
    assert len(_rows(database_url)) == 1


def test_two_reports_without_a_key_are_two_reports(client: TestClient, database_url: str) -> None:
    """No key means no claim of sameness. Deduplicating identical-looking bodies would answer a
    second bug with the first one's `ref` — the `OME-970` shape."""
    first = _post(client, a_report())
    second = _post(client, a_report())

    assert first.json()["ref"] != second.json()["ref"]
    assert len(_rows(database_url)) == 2


def test_a_storage_failure_answers_503_and_stores_nothing(
    client: TestClient, database_url: str
) -> None:
    """The one status that tells a client to stop trusting this service with the report and
    write it to disk instead (spec §8). Answering anything else — a `500`, or a `202` for a row
    that does not exist — makes a reporter believe a bug was filed when it was not."""
    client.app.state.report_pipeline = _unavailable_pipeline()  # type: ignore[attr-defined]

    response = _post(client, a_report())

    assert response.status_code == 503
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert _rows(database_url) == []


def test_the_503_tells_the_client_to_keep_the_report(client: TestClient) -> None:
    """A generic "service unavailable" is indistinguishable from a transient blip the client
    should just retry through. This one has to say that nothing was accepted."""
    client.app.state.report_pipeline = _unavailable_pipeline()  # type: ignore[attr-defined]

    detail = _post(client, a_report()).json()["detail"]

    assert "keep the report" in detail


def test_the_503_body_says_nothing_about_the_database(client: TestClient) -> None:
    """The problem document travels over an unauthenticated response. What failed inside the
    store belongs in the log, next to the original exception the `raise ... from` kept."""
    client.app.state.report_pipeline = _unavailable_pipeline()  # type: ignore[attr-defined]

    body = _post(client, a_report()).text

    assert "sqlite" not in body.lower()
    assert "database is gone" not in body


def test_a_rejected_report_is_never_written(client: TestClient, database_url: str) -> None:
    """Spec §4 rejects rather than stores, and the structural guarantee is that classification
    runs at the route, before the pipeline exists to be called (plan §2.7)."""
    response = _post(
        client, a_report(error={"type": "E", "message": "m", "details": {"prompt": "write a poem"}})
    )

    assert response.status_code == 422
    assert _rows(database_url) == []


def test_a_report_over_the_body_cap_is_never_written(client: TestClient, database_url: str) -> None:
    """The cap is enforced pre-routing, so nothing downstream ever sees the bytes — including
    the store, which is the point of bounding before believing."""
    response = _post(client, a_report(note="n" * (64 * 1024)))

    assert response.status_code == 413
    assert _rows(database_url) == []


def test_a_reply_to_over_the_column_width_is_422_and_stores_nothing(
    client: TestClient, database_url: str
) -> None:
    """A client-controlled field must never be able to manufacture a `503`. Unbounded at the
    route it reached a `varchar(320)`, tortoise's validator raised, and every ORM failure leaves
    the store as `StorageUnavailable` — so a 412-character address inside a body well under the
    64 KiB cap was answered with the one status spec §8 defines as *retry unchanged*. Bounded at
    the schema it is what §2.3's table already calls it: a schema violation with a field pointer.
    """
    response = _post(client, a_report(reply_to="a" * 400 + "@example.org"))

    assert response.status_code == 422
    assert "/reply_to" in response.json()["detail"]
    assert _rows(database_url) == []


def test_a_reply_to_at_the_column_width_is_stored(client: TestClient, database_url: str) -> None:
    """The bound is RFC 5321's and the column's, so the longest real address still gets through —
    a route stricter than the column would refuse a report the database would have taken."""
    address = "a" * (EMAIL_MAX_LENGTH - len("@example.org")) + "@example.org"

    assert _post(client, a_report(reply_to=address)).status_code == 202
    assert _rows(database_url)[0]["reply_to"] == address


def test_a_reply_to_that_is_not_an_address_is_accepted_rather_than_losing_the_report(
    client: TestClient, database_url: str
) -> None:
    """The decision the two cases above do NOT make: `reply_to` is never syntax-checked, here or
    anywhere downstream (`ReportDocument.reply_to`). Spec §9's caller table already says
    "accepted, unverified" for both caller classes, and the arithmetic is one-sided — a `422`
    throws away the error, the traceback, the client versions and the trace id over the one field
    nothing is authorized on, while a typo'd address still leaves a report somebody can act on.

    The `422` above is a LENGTH refusal and this test is what stops it being read as licence for a
    syntax one: that bound exists because the column is `varchar(320)` and an over-long value
    reached tortoise's validator, where every ORM failure becomes a `503` — the one status spec §8
    defines as *retry unchanged*. Length has a wrong answer; shape does not.
    """
    assert _post(client, a_report(reply_to="not-an-email")).status_code == 202
    assert _rows(database_url)[0]["reply_to"] == "not-an-email"


def test_an_over_long_idempotency_key_is_400_and_stores_nothing(
    client: TestClient, database_url: str
) -> None:
    """Same failure as `reply_to`, arriving through a header rather than the body — and answered
    `400` because a header is not the report's schema. What both share is that the client can fix
    it, so neither may wear the status that tells a client to keep retrying unchanged."""
    response = _post(client, a_report(), **{"Idempotency-Key": "k" * 4096})

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert _rows(database_url) == []


def test_one_callers_idempotency_key_cannot_resolve_another_callers_report(
    mesh_client: TestClient, database_url: str
) -> None:
    """`Idempotency-Key` is a claim, not a credential — the same rule spec §7 states for
    `trace_id`, and it binds here because `POST /v1/reports` is unauthenticated and nothing makes
    a client pick a UUID over `1`.

    Resolved from the raw string across every caller, a stranger who guessed a key was answered
    `200` with the FIRST caller's `ref` — and their own report was silently never stored. That is
    enumeration in one direction and report suppression in the other, from one defect.
    """
    victim = _post(mesh_client, a_report(note="mine"), **_mesh("victim@openmined.org", "1"))
    stranger = _post(mesh_client, a_report(note="theirs"), **_mesh("stranger@openmined.org", "1"))

    assert (victim.status_code, stranger.status_code) == (202, 202)
    assert stranger.json()["ref"] != victim.json()["ref"]
    assert len(_rows(database_url)) == 2


def test_the_same_caller_replaying_one_key_still_gets_one_report(
    mesh_client: TestClient, database_url: str
) -> None:
    """The other half, and the reason scoping is not simply "stop deduplicating": within a
    caller the window still collapses a double-click into one report and one ticket (spec §5)."""
    first = _post(mesh_client, a_report(), **_mesh("engineer@openmined.org", "1"))
    second = _post(mesh_client, a_report(), **_mesh("engineer@openmined.org", "1"))

    assert (first.status_code, second.status_code) == (202, 200)
    assert second.json()["ref"] == first.json()["ref"]
    assert len(_rows(database_url)) == 1


def test_the_stored_dedup_key_is_not_the_string_the_client_chose(
    mesh_client: TestClient, database_url: str
) -> None:
    """The raw header is free text on an unauthenticated request. Scoping is done by hashing
    precisely so it never lands in a column, and so the column stays one unique varchar rather
    than needing a composite constraint."""
    _post(mesh_client, a_report(), **_mesh("engineer@openmined.org", "guessable-1"))

    assert _rows(database_url)[0]["idempotency_key"] != "guessable-1"


def test_the_row_carries_the_retry_columns_a_later_item_will_read(
    client: TestClient, database_url: str
) -> None:
    """`0001_initial` is greenfield exactly once (plan §2.3), so the columns `OME-1009` and
    `OME-1010` need are already here and already correct: the inline attempt counted, both
    deadlines NOT NULL, and no ticket — `QueueSink` returns none, by design."""
    _post(client, a_report())

    row = _rows(database_url)[0]
    assert row["attempts"] == 1
    assert row["next_attempt_at"] is not None
    assert row["lease_expires_at"] is not None
    assert (row["ticket_id"], row["ticket_url"]) == (None, None)
    assert row["request_fingerprint"]
