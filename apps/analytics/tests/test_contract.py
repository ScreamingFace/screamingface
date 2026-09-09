from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from analytics_service.contract import InvalidPayload, parse_batch


@pytest.mark.parametrize(
    "name,outcomes",
    [
        ("evaluation_started", [None]),
        ("submission_started", [None]),
        ("evaluation_finished", ["succeeded", "completed_with_failures", "failed", "cancelled"]),
        ("submission_finished", ["succeeded", "failed", "cancelled"]),
    ],
)
def test_event_forms(envelope, name, outcomes):
    event = envelope["events"][0]
    event["event"] = name
    event["workflow"] = "submission" if name.startswith("submission") else "raw_url4"
    for outcome in outcomes:
        if outcome:
            event.update(outcome=outcome, duration_bucket="1_10m")
        assert len(parse_batch(envelope).events) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("origin", "unknown"),
        ("usage_mode", "mixed"),
        ("usage_mode", "unknown"),
        ("event_id", "not-an-id"),
        ("session_id", 3),
        ("sdk_version", "secret host name"),
        ("outcome", "succeeded"),
        ("duration_bucket", None),
        ("report_ok", True),
        ("prompt", "private"),
        ("$ip", "127.0.0.1"),
        ("properties", {"email": "private"}),
        ("workflow", "submission"),
        ("timestamp", "2026-01-01T00:00:00.000Z"),
    ],
)
def test_invalid_event(envelope, field, value):
    envelope["events"][0][field] = value
    with pytest.raises(InvalidPayload):
        parse_batch(envelope)


@pytest.mark.parametrize("field", ["origin", "usage_mode", "persistent_id", "session_id"])
def test_required_fields(envelope, field):
    del envelope["events"][0][field]
    with pytest.raises(InvalidPayload):
        parse_batch(envelope)


@pytest.mark.parametrize(
    "field,value",
    [
        ("consent_granted", False),
        ("consent_granted", 1),
        ("consent_version", "2"),
        ("schema_version", True),
        ("schema_version", "1"),
        ("extra", "private"),
        ("events", []),
    ],
)
def test_invalid_envelope(envelope, field, value):
    envelope[field] = value
    with pytest.raises(InvalidPayload):
        parse_batch(envelope)


def test_scope_and_duplicates(envelope):
    event = envelope["events"][0]
    event["id_scope"] = "session"
    with pytest.raises(InvalidPayload):
        parse_batch(envelope)
    del event["persistent_id"]
    envelope["events"].append(deepcopy(event))
    assert len(parse_batch(envelope).events) == 1
    envelope["events"][1]["origin"] = "cli"
    with pytest.raises(InvalidPayload):
        parse_batch(envelope)


def test_future_and_batch_size(envelope):
    envelope["events"] *= 21
    with pytest.raises(InvalidPayload):
        parse_batch(envelope)
    envelope["events"] = envelope["events"][:1]
    envelope["events"][0]["timestamp"] = (
        (datetime.now(UTC) + timedelta(minutes=6))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    with pytest.raises(InvalidPayload):
        parse_batch(envelope)


@pytest.mark.parametrize(
    "changes",
    [
        {"event": "evaluation_finished"},
        {
            "event": "submission_finished",
            "workflow": "submission",
            "outcome": "completed_with_failures",
            "duration_bucket": "1_10m",
        },
        {"timestamp": "2026-99-99T10:00:00.000Z"},
    ],
)
def test_terminal_combinations(envelope, changes):
    envelope["events"][0].update(changes)
    with pytest.raises(InvalidPayload):
        parse_batch(envelope)
