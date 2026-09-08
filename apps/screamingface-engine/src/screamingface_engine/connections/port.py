"""Provider-connection domain types and the Engine-facing port.

The control plane exposes connection state without exposing aigateway's account IDs,
credential locators, or provider response bodies. Concrete adapters translate their
upstream into these deliberately small values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

AuthMethod = Literal["api_key", "oauth"]
ConnectionStatus = Literal[
    "not_connected",
    "pending",
    "connected",
    "needs_reauth",
    "error",
]


@dataclass(frozen=True, slots=True)
class Caller:
    """Verified identity headers associated with one Engine request.

    FEATURE (OME-1119): also carries the request's own ``traceparent`` and routing ``profile``,
    which the adapter renders onto every upstream call it makes on this caller's behalf.

    WHY here rather than a ContextVar: this object already IS the per-request scope, one
    instance per inbound Engine request, so the value cannot be read by a request that did not
    carry it. The run-mode connector uses a ContextVar precisely because it has no such object —
    its world is cached across runs.
    """

    identity: Mapping[str, str] = field(default_factory=dict)
    traceparent: str | None = None
    profile: str | None = None


@dataclass(frozen=True, slots=True)
class Connection:
    """The safe, public status of one provider connection."""

    provider: str
    display_name: str
    auth_methods: tuple[AuthMethod, ...]
    status: ConnectionStatus
    auth_method: AuthMethod | None = None
    account_label: str | None = None


@dataclass(frozen=True, slots=True)
class OAuthAuthorization:
    """A bounded browser authorization created by AI Gateway."""

    provider: str
    authorize_url: str
    expires_in: int


class ConnectionError(Exception):
    """A safe connection failure with its public HTTP mapping."""

    status = 502
    title = "Bad Gateway"
    detail = "the provider connection could not be updated"

    def __init__(self, detail: str | None = None) -> None:
        # Accepting a caller message is useful for logs/tests, but public routes always use
        # the class-level safe detail. This prevents an upstream body or API key from leaking.
        self.internal_detail = detail
        super().__init__(self.detail)


class ConnectionRejected(ConnectionError):
    """The caller identity or provider credential was rejected."""

    status = 401
    title = "Unauthorized"
    detail = "the provider connection was rejected"


class ConnectionNotFound(ConnectionError):
    """The requested provider is not exposed by this Engine."""

    status = 404
    title = "Not Found"
    detail = "the requested provider is not available"


class ConnectionMethodUnsupported(ConnectionError):
    """The provider exists but cannot accept the requested credential method."""

    status = 400
    title = "Bad Request"
    detail = "the provider does not support the requested connection method"


class ConnectionConflict(ConnectionError):
    """AI Gateway connection state conflicts with the requested operation."""

    status = 409
    title = "Conflict"
    detail = "provider connection state conflicts with this operation"


class ConnectionAlreadyConnected(ConnectionError):
    """Changing authentication methods requires an explicit disconnect."""

    status = 409
    title = "Conflict"
    detail = "the provider is already connected; disconnect it before changing authentication"


class ConnectionRateLimited(ConnectionError):
    """AI Gateway refused the operation because it was rate limited."""

    status = 429
    title = "Too Many Requests"
    detail = "provider connection requests are temporarily rate limited"


class ConnectionBadResponse(ConnectionError):
    """AI Gateway returned a malformed or otherwise unusable response."""

    status = 502
    title = "Bad Gateway"
    detail = "AI Gateway returned an unusable provider connection response"


class ConnectionUnavailable(ConnectionError):
    """AI Gateway could not be reached."""

    status = 503
    title = "Service Unavailable"
    detail = "AI Gateway is unavailable"


class ConnectionTimeout(ConnectionError):
    """AI Gateway did not respond before the Engine timeout."""

    status = 504
    title = "Gateway Timeout"
    detail = "AI Gateway did not respond in time"


@runtime_checkable
class Connections(Protocol):
    """Provider-connection operations required by the Engine REST surface."""

    async def list(self, caller: Caller) -> tuple[Connection, ...]: ...

    async def connect(self, caller: Caller, provider: str, api_key: str) -> Connection: ...

    async def start_oauth(self, caller: Caller, provider: str) -> OAuthAuthorization: ...

    async def disconnect(self, caller: Caller, provider: str) -> Connection: ...

    async def aclose(self) -> None: ...


__all__ = [
    "AuthMethod",
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
    "ConnectionStatus",
    "ConnectionTimeout",
    "ConnectionUnavailable",
    "Connections",
    "OAuthAuthorization",
]
