"""The replay pin grammar (contract C6, `prd/replay-pinned-run.md` section 3.1).

FEATURE: OME-1307 (E14) `evaluate(replay=...)`. A pin names the result a run replays:
`result:<uuid>`, `score:<uuid>`, `<name>`, `<name>@r<N>`, `<name>@<date or time>`.

INVARIANT (D7 X-21): the grammar is MIRRORED, never imported (C11: the SDK does not import the
scoreboard). It must accept and refuse exactly the forms of the Scoreboard parser
(`apps/scoreboard/src/scoreboard/core/registry/pins.py` and `names.py`), so a pin the SDK lets
through is never a pin the board calls malformed, and the reverse. A time with no UTC offset is
refused on both sides.
AIDEV-NOTE: change this file and the scoreboard parser together.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

# INVARIANT: mirrors the system-name rule of erd.md section 2.3.1 (lowercase, then this regex).
_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
# WHY nine digits at most: the Scoreboard caps a revision number there (`pins.py`).
_REVISION = re.compile(r"^r([1-9][0-9]{0,8})$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

type _PinKind = Literal["result", "score", "name", "revision", "date"]
_UUID_FORMS: tuple[tuple[str, Literal["result", "score"]], ...] = (
    ("result:", "result"),
    ("score:", "score"),
)


@dataclass(frozen=True, slots=True)
class _ReplayPin:
    text: str  # the stripped pin, sent unchanged to the scoreboard
    kind: _PinKind


def parse_replay_pin(value: object) -> _ReplayPin:
    """The checked pin, or `TypeError` (not text) / `ValueError` (not a pin form)."""
    if not isinstance(value, str):
        raise TypeError("replay must be a pin string")
    text = value.strip()
    if not text:
        raise _invalid(value, "the pin is empty")
    for prefix, kind in _UUID_FORMS:
        if text.startswith(prefix):
            _check_uuid(value, text.removeprefix(prefix))
            return _ReplayPin(text, kind)
    name, separator, qualifier = text.partition("@")
    _check_name(value, name)
    if not separator:
        return _ReplayPin(text, "name")
    return _ReplayPin(text, _qualifier_kind(value, qualifier))


def _invalid(value: object, why: str) -> ValueError:
    return ValueError(f"invalid replay pin {value!r}: {why}")


def _check_uuid(value: object, rest: str) -> None:
    try:
        uuid.UUID(rest)
    except ValueError:
        raise _invalid(value, "expected a UUID after the prefix") from None


def _check_name(value: object, name: str) -> None:
    # WHY the ASCII check runs before `lower()`: KELVIN SIGN lowercases to the ASCII "k", and the
    # Scoreboard refuses non-ASCII text first.
    if not name.isascii() or _NAME.fullmatch(name.lower()) is None:
        raise _invalid(
            value,
            "a system name has 1 to 64 characters: a-z, 0-9, '.', '_' and '-', "
            "starting and ending with a letter or digit",
        )


def _qualifier_kind(value: object, qualifier: str) -> _PinKind:
    if _REVISION.fullmatch(qualifier):
        return "revision"
    try:
        if _DATE.fullmatch(qualifier):
            date.fromisoformat(qualifier)
            return "date"
        moment = datetime.fromisoformat(qualifier.replace("Z", "+00:00"))
    except ValueError:
        raise _invalid(value, "the part after '@' is not r<N> or an ISO-8601 date") from None
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise _invalid(value, "a pin time needs a UTC offset")
    return "date"
