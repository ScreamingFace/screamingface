"""The capture and call-key headers, and how an exception handler learns the capture (OME-1307).

An HTTPException can carry the header itself. A ``CredentialBlobMutationConflict`` or an unexpected
exception is re-raised unchanged and rendered by an app-level handler, so the route leaves the
header on ``request.state`` and those handlers add it.

It also names the one response header an error entry keeps for its replay: ``Retry-After``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

COPY_HEADER = "X-AIGW-Frozen-Copy"
CAPTURE_HEADER = "X-AIGW-Capture"
# The call key of a frozen-copy request (Q27, design §4.2). The engine sends both on capture and on
# replay, so both runs name each call the same way.
CASE_KEY_HEADER = "X-AIGW-Case-Key"
OCCURRENCE_HEADER = "X-AIGW-Call-Occurrence"
RETRY_AFTER_HEADER = "Retry-After"
# The key of an error entry's kept response headers: only Retry-After, and only when sent.
STORED_HEADERS_FIELD = "headers"
_STATE_ATTR = "aigw_capture_headers"
_CASE_KEY = re.compile(r"[0-9a-f]{32}")
# A regex, not int(): int() would take "+3", " 3", "1_0" and non-ASCII digits as numbers.
_OCCURRENCE = re.compile(r"[0-9]{1,9}")


class MalformedCallKey(Exception):
    """A call-key header is missing or not in the form design §4.2 names. Its text is the header."""


def publish_capture_headers(request: Any, headers: dict[str, str]) -> None:
    setattr(request.state, _STATE_ATTR, headers)


def published_capture_headers(request: Any) -> dict[str, str]:
    """The headers a route published for this request; empty when it published none."""
    return dict(getattr(request.state, _STATE_ATTR, None) or {})


def parse_call_key(headers: Mapping[str, str]) -> tuple[str, int]:
    """The case key and the occurrence of one request (design §4.2, Q27).

    The case key is absent (``""``) or 32 lowercase hex characters. The occurrence is required and
    is 1 to 9 ASCII digits. Anything else is malformed: the caller decides what that means (a
    refusal on capture, a 400 on replay). It is never read as absent.
    """
    case_key = headers.get(CASE_KEY_HEADER, "")
    if case_key and _CASE_KEY.fullmatch(case_key) is None:
        raise MalformedCallKey(CASE_KEY_HEADER)
    occurrence = headers.get(OCCURRENCE_HEADER)
    if occurrence is None or _OCCURRENCE.fullmatch(occurrence) is None:
        raise MalformedCallKey(OCCURRENCE_HEADER)
    return case_key, int(occurrence)
