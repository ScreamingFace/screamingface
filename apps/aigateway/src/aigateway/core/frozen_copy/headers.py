"""The capture response header, and how an exception handler learns it (OME-1307, design §4.2).

An HTTPException can carry the header itself. A ``CredentialBlobMutationConflict`` or an unexpected
exception is re-raised unchanged and rendered by an app-level handler, so the route leaves the
header on ``request.state`` and those handlers add it.

It also names the one response header an error entry keeps for its replay: ``Retry-After``.
"""

from __future__ import annotations

from typing import Any

COPY_HEADER = "X-AIGW-Frozen-Copy"
CAPTURE_HEADER = "X-AIGW-Capture"
RETRY_AFTER_HEADER = "Retry-After"
# The engine's send-time slot of a capture request (Q27, design §5.3 item 1). The engine reserves
# the occurrence of one logical call when it SENDS it, and states it here; the entry stores it and
# replay serves successes by it. Absent on a capture request: the entry falls back to completion
# order (`seq`), the behaviour of a gateway before Q27. Absent means legacy, never "unset".
CAPTURE_OCCURRENCE_HEADER = "X-AIGW-Capture-Occurrence"
# The key of an error entry's kept response headers: only Retry-After, and only when sent.
STORED_HEADERS_FIELD = "headers"
_STATE_ATTR = "aigw_capture_headers"


def publish_capture_headers(request: Any, headers: dict[str, str]) -> None:
    setattr(request.state, _STATE_ATTR, headers)


def published_capture_headers(request: Any) -> dict[str, str]:
    """The headers a route published for this request; empty when it published none."""
    return dict(getattr(request.state, _STATE_ATTR, None) or {})


def parse_capture_occurrence(raw: str | None) -> int | None:
    """The caller's send-time slot, or ``None`` when it is absent or not a usable slot.

    Capture is best effort: a malformed or negative value reads as absent (design §4.2), so a
    bad header never fails the call — the entry then falls back to completion order.
    """
    if raw is None:
        return None
    try:
        occurrence = int(raw)
    except ValueError:
        return None
    return occurrence if occurrence >= 0 else None
