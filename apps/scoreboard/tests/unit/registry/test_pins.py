"""Pin parsing: SR-20 (parse half).

FEATURE: OME-1307 (E14) — `name`, `name@r<N>`, `name@<date or time>`. The `result:` and `score:`
forms belong to SB-grants (RP-6 to RP-8).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scoreboard.core.registry import DatePin, InvalidPin, NamePin, RevisionPin, parse_pin


def test_sr20_a_bare_name_is_a_name_pin() -> None:
    assert parse_pin("kevins-best") == NamePin("kevins-best")


def test_sr20_a_revision_qualifier_is_a_revision_pin() -> None:
    assert parse_pin("kevins-best@r1") == RevisionPin("kevins-best", 1)
    assert parse_pin("kevins-best@r123456789") == RevisionPin("kevins-best", 123456789)


def test_sr20_a_date_qualifier_means_the_end_of_that_day_utc() -> None:
    assert parse_pin("kevins-best@2026-09-01") == DatePin(
        "kevins-best", datetime(2026, 9, 1, 23, 59, 59, 999999, tzinfo=UTC)
    )


def test_sr20_a_time_with_an_offset_is_converted_to_utc_and_the_name_is_lowercased() -> None:
    pin = parse_pin("Kevins-Best@2026-09-01T10:00:00+02:00")

    assert pin == DatePin("kevins-best", datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC))
    assert isinstance(pin, DatePin) and pin.at.utcoffset() == UTC.utcoffset(None)


@pytest.mark.parametrize(
    "raw",
    [
        "x@r0",
        "x@r01",
        "x@r-1",
        "x@r1234567890",  # ten digits: over the r<N> grammar
        "x@",
        "x@2026-13-01",
        "x@2026-09-01T10:00:00",  # no UTC offset (X-21)
        "x@garbage",
        "result:0b1f5c1e-6a56-4b4f-8b0e-0e2f0f3d6f0a",
        "a/b@r1",
        "",
    ],
)
def test_sr20_a_bad_pin_is_invalid(raw: str) -> None:
    with pytest.raises(InvalidPin) as info:
        parse_pin(raw)

    assert info.value.code == "invalid_replay_pin"
    assert info.value.pin == raw


def test_sr20_the_message_says_what_is_wrong() -> None:
    with pytest.raises(InvalidPin, match="empty pin qualifier"):
        parse_pin("x@")
    with pytest.raises(InvalidPin, match="UTC offset"):
        parse_pin("x@2026-09-01T10:00:00")
    with pytest.raises(InvalidPin, match=r"r<N>"):
        parse_pin("x@nope")
