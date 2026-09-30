"""Opaque `(submitted_at, id)` cursors for the results list (C10).

FEATURE: OME-1307 (E14). INVARIANT: pure. Standard library only.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class InvalidCursor(Exception):
    """The text is not a cursor this service made (-> 422 invalid_cursor)."""


@dataclass(frozen=True, slots=True)
class Cursor:
    submitted_at: datetime
    id: UUID


def encode_cursor(cursor: Cursor) -> str:
    """Urlsafe base64, no padding, of `{"t": <submitted_at isoformat>, "i": <id>}`."""
    body = json.dumps(
        {"t": cursor.submitted_at.isoformat(), "i": str(cursor.id)}, separators=(",", ":")
    )
    return base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")


def decode_cursor(text: str) -> Cursor:
    """INVARIANT: only the two keys `t` and `i`; any other text is `InvalidCursor`."""
    try:
        padded = text + "=" * (-len(text) % 4)
        body = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if not isinstance(body, dict) or set(body) != {"t", "i"}:
            raise InvalidCursor
        return Cursor(datetime.fromisoformat(body["t"]), UUID(body["i"]))
    except (binascii.Error, ValueError, TypeError, UnicodeDecodeError) as exc:
        raise InvalidCursor from exc
