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
# The key of an error entry's kept response headers: only Retry-After, and only when sent.
STORED_HEADERS_FIELD = "headers"
_STATE_ATTR = "aigw_capture_headers"


def publish_capture_headers(request: Any, headers: dict[str, str]) -> None:
    setattr(request.state, _STATE_ATTR, headers)


def published_capture_headers(request: Any) -> dict[str, str]:
    """The headers a route published for this request; empty when it published none."""
    return dict(getattr(request.state, _STATE_ATTR, None) or {})
