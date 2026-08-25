"""Secret-free translation of AI Gateway HTTP failures."""

from __future__ import annotations

import httpx

from screamingface_engine.connections.port import (
    ConnectionBadResponse,
    ConnectionConflict,
    ConnectionNotFound,
    ConnectionRateLimited,
    ConnectionRejected,
    ConnectionTimeout,
    ConnectionUnavailable,
)


def raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 300:
        return
    error = {
        # WHY: capability is checked before credentials leave the Engine, while AI Gateway also
        # uses 400 for malformed credentials. Upstream 400 is therefore a rejection, not proof
        # that the advertised method is unsupported.
        400: ConnectionRejected,
        401: ConnectionRejected,
        403: ConnectionRejected,
        404: ConnectionNotFound,
        409: ConnectionConflict,
        422: ConnectionRejected,
        429: ConnectionRateLimited,
        503: ConnectionUnavailable,
        504: ConnectionTimeout,
    }.get(response.status_code, ConnectionBadResponse)
    raise error()


__all__ = ["raise_for_status"]
