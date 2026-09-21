"""Strict decoder for the gateway's caller-scoped provider-access availability listing.

FEATURE (OME-1138 Stage A4, OME-1245): the Hosted Engine reads ``GET /v1/provider-access`` —
rows of ``provider`` and ``status`` only (D17) — instead of aggregating legacy Profiles locally.
"""

from __future__ import annotations

from typing import Any, cast, get_args

from screamingface_engine.connections.port import ConnectionBadResponse, ConnectionStatus
from screamingface_engine.connections.provider_id import is_provider_id

# WHY derived rather than spelled out: the route publishes the Engine's own ``ConnectionStatus``
# family, so the accepted vocabulary and the public status type cannot drift apart.
_STATUSES: frozenset[str] = frozenset(get_args(ConnectionStatus))


def decode_provider_access(body: dict[str, Any]) -> dict[str, ConnectionStatus]:
    """Map the listing's rows to ``provider -> status``; anything else is a bad response.

    INVARIANT: a malformed body is refused, never guessed — a bad response, 502, never a made-up
    status. A provider that appears twice is malformed for the same reason: two rows would leave
    the status to a guess. Additive envelope or row fields are ignored and never surface, so the
    gateway may grow the listing without breaking a deployed Engine.
    """
    rows = body.get("providers")
    if not isinstance(rows, list):
        raise ConnectionBadResponse()
    statuses: dict[str, ConnectionStatus] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ConnectionBadResponse()
        provider = row.get("provider")
        status = row.get("status")
        if (
            not is_provider_id(provider)
            or not isinstance(status, str)
            or status not in _STATUSES
            or provider in statuses
        ):
            raise ConnectionBadResponse()
        statuses[provider] = cast(ConnectionStatus, status)
    return statuses


__all__ = ["decode_provider_access"]
