"""Provider-connection subsystem and production composition helper."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import (
    Caller,
    Connection,
    ConnectionAlreadyConnected,
    ConnectionBadResponse,
    ConnectionConflict,
    ConnectionError,
    ConnectionMethodUnsupported,
    ConnectionNotFound,
    ConnectionRateLimited,
    ConnectionRejected,
    Connections,
    ConnectionTimeout,
    ConnectionUnavailable,
)

_UPSTREAM_TIMEOUT_S = 10.0


class _ConnectionSettings(Protocol):
    aigateway_base_url: str | None


def _default_client(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=_UPSTREAM_TIMEOUT_S)


def build_connections(
    settings: _ConnectionSettings,
    *,
    mutable: bool,
    client_factory: Callable[[str], httpx.AsyncClient] = _default_client,
) -> Connections | None:
    """Build the AI Gateway adapter, or disable the endpoints when no upstream is configured.

    INVARIANT (D15): ``mutable`` is deliberately required — each composition root states in
    plain sight whether its Engine may write provider connections (Local) or only reports the
    caller's provider access (Hosted).
    """

    if not settings.aigateway_base_url:
        return None
    return AigatewayConnections(client_factory(settings.aigateway_base_url), mutable=mutable)


__all__ = [
    "Caller",
    "Connection",
    "ConnectionAlreadyConnected",
    "ConnectionBadResponse",
    "ConnectionConflict",
    "ConnectionError",
    "ConnectionMethodUnsupported",
    "ConnectionNotFound",
    "ConnectionRateLimited",
    "ConnectionRejected",
    "ConnectionTimeout",
    "ConnectionUnavailable",
    "Connections",
    "build_connections",
]
