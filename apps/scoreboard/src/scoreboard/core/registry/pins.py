"""Parsing of the three system pin forms (PRD §3.1, erd.md §6.4).

FEATURE: OME-1307 (E14) — `name`, `name@r<N>` and `name@<date or time>`.
AIDEV-NOTE: the `result:<uuid>` and `score:<uuid>` forms are SB-grants' (RP-6 to RP-8). They
are not parsed here, so `parse_pin("result:...")` raises `InvalidPin`; SB-grants tries its own
forms before it calls this function.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time

from .errors import InvalidPin, InvalidSystemName
from .model import DatePin, NamePin, Pin, RevisionPin
from .names import normalize_system_name

_REVISION_RE = re.compile(r"^r([1-9][0-9]{0,8})$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_pin(raw: str) -> Pin:
    name_part, sep, qualifier = raw.partition("@")
    try:
        name = normalize_system_name(name_part)
    except InvalidSystemName as exc:
        raise InvalidPin(raw, exc.message) from exc
    if not sep:
        return NamePin(name)
    if not qualifier:
        raise InvalidPin(raw, "empty pin qualifier")
    revision = _REVISION_RE.match(qualifier)
    if revision:
        return RevisionPin(name, int(revision.group(1)))
    return DatePin(name, _parse_time(raw, qualifier))


def _parse_time(raw: str, qualifier: str) -> datetime:
    try:
        if _DATE_RE.match(qualifier):
            # RP-D7: a date-only pin means the end of that day, UTC.
            return datetime.combine(
                date.fromisoformat(qualifier), time(23, 59, 59, 999999), tzinfo=UTC
            )
        value = datetime.fromisoformat(qualifier)
    except ValueError as exc:
        raise InvalidPin(raw, "not a revision (r<N>) or an ISO-8601 date") from exc
    # INVARIANT (X-21): a time with no UTC offset is refused on both sides (SDK and scoreboard).
    if value.tzinfo is None:
        raise InvalidPin(raw, "a pin time needs a UTC offset")
    return value.astimezone(UTC)
