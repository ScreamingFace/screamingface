"""``as_utc`` gives one aware UTC form for a naive time and an aware time (OME-1947)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from aigateway.core.frozen_copy.times import as_utc


def test_a_naive_time_is_read_as_utc() -> None:
    value = as_utc(datetime(2026, 11, 17, 12, 0, 0))

    assert value == datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)
    assert value.utcoffset() == timedelta(0)


def test_an_aware_time_is_converted_to_utc() -> None:
    value = as_utc(datetime(2026, 11, 17, 14, 0, 0, tzinfo=timezone(timedelta(hours=2))))

    assert value.isoformat() == "2026-11-17T12:00:00+00:00"


def test_a_naive_and_an_aware_form_of_one_time_give_the_same_text() -> None:
    naive = datetime(2026, 11, 17, 12, 0, 0, 123456)

    assert as_utc(naive).isoformat() == as_utc(naive.replace(tzinfo=UTC)).isoformat()
