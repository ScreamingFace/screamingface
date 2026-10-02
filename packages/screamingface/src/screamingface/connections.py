"""Public provider-connection values and default-client convenience functions."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from screamingface.errors import ProviderConnectionError

type AuthMethod = Literal["api_key", "oauth"]
type ConnectionStatus = Literal[
    "not_connected",
    "pending",
    "connected",
    "needs_reauth",
    "error",
    # FEATURE (OME-1250): authenticates, but the provider cannot serve it right now (402 /
    # quota). Distinct from `error`, which means the credential itself was rejected.
    "unavailable",
]

_METHODS = frozenset({"api_key", "oauth"})
# AIDEV-NOTE: STRICT by owner decision (2026-10-02) — an unknown status is refused, never
# guessed. A new value ships here (published) BEFORE the gateway emits it.
_STATUSES = frozenset(
    {"not_connected", "pending", "connected", "needs_reauth", "error", "unavailable"}
)
_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9_-]*\Z", re.ASCII)


def _provider_id(value: object) -> str:
    """Return one canonical provider path segment or reject it before request construction."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("provider must be a non-empty string")
    selected = value.strip()
    if _PROVIDER_ID.fullmatch(selected) is None:
        raise ValueError("provider must be a lowercase ASCII identifier")
    return selected


@dataclass(frozen=True, slots=True)
class Connection:
    """Sanitized provider state advertised by the configured SF Engine."""

    provider: str
    display_name: str
    auth_methods: tuple[AuthMethod, ...]
    status: ConnectionStatus
    auth_method: AuthMethod | None
    account_label: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider, str)
            or not self.provider.strip()
            or not isinstance(self.display_name, str)
            or not self.display_name.strip()
        ):
            raise ValueError("connection provider and display_name must be non-empty")
        if _provider_id(self.provider) != self.provider:
            raise ValueError("connection provider must be canonical")
        if not self.auth_methods or any(method not in _METHODS for method in self.auth_methods):
            raise ValueError("connection auth_methods contain an unsupported method")
        if self.status not in _STATUSES:
            raise ValueError(f"unknown connection status {self.status!r}")
        if self.auth_method is not None and self.auth_method not in self.auth_methods:
            raise ValueError("connection auth_method is not advertised by its provider")
        if self.account_label is not None and not self.account_label.strip():
            raise ValueError("connection account_label must be non-empty or None")


@dataclass(frozen=True, slots=True)
class OAuthFlow:
    """A bounded provider OAuth authorization started through one Client."""

    provider: str
    authorize_url: str
    expires_in: int
    status: Literal["pending"] = "pending"
    _get: Callable[[], Connection] | None = field(default=None, repr=False, compare=False)
    _disconnect: Callable[[], Connection] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _expires_at: float = field(default=0.0, repr=False, compare=False)

    def wait(
        self,
        *,
        poll_interval: float = 0.5,
        timeout: float | None = None,
    ) -> Connection:
        """Block until authorization completes or the bounded flow expires."""

        interval = _poll_interval(poll_interval)
        timeout_seconds = _wait_timeout(timeout)
        get = _required_callback(self._get)
        deadline = _wait_deadline(self._expires_at, timeout_seconds)
        while time.monotonic() <= deadline:
            connection = get()
            if connection.status != "pending":
                return connection
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
        if timeout_seconds is not None and deadline < self._expires_at:
            raise _wait_expired(self.provider)
        raise _expired(self.provider)

    def cancel(self) -> Connection:
        """Cancel this authorization; repeated cancellation remains harmless."""

        return _required_callback(self._disconnect)()

    @property
    def expired(self) -> bool:
        """Whether the Engine-advertised authorization lifetime has elapsed."""

        return time.monotonic() > self._expires_at


@dataclass(frozen=True, slots=True)
class AsyncOAuthFlow:
    """Asynchronous counterpart of :class:`OAuthFlow`."""

    provider: str
    authorize_url: str
    expires_in: int
    status: Literal["pending"] = "pending"
    _get: Callable[[], Awaitable[Connection]] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _disconnect: Callable[[], Awaitable[Connection]] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _expires_at: float = field(default=0.0, repr=False, compare=False)

    async def wait(
        self,
        *,
        poll_interval: float = 0.5,
        timeout: float | None = None,
    ) -> Connection:
        """Wait asynchronously until authorization completes or expires."""

        interval = _poll_interval(poll_interval)
        timeout_seconds = _wait_timeout(timeout)
        get = _required_callback(self._get)
        deadline = _wait_deadline(self._expires_at, timeout_seconds)
        while time.monotonic() <= deadline:
            connection = await get()
            if connection.status != "pending":
                return connection
            await asyncio.sleep(min(interval, max(0.0, deadline - time.monotonic())))
        if timeout_seconds is not None and deadline < self._expires_at:
            raise _wait_expired(self.provider)
        raise _expired(self.provider)

    async def cancel(self) -> Connection:
        """Cancel this authorization; repeated cancellation remains harmless."""

        return await _required_callback(self._disconnect)()

    @property
    def expired(self) -> bool:
        """Whether the Engine-advertised authorization lifetime has elapsed."""

        return time.monotonic() > self._expires_at


def _poll_interval(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("poll_interval must be a non-negative number")
    if value < 0:
        raise ValueError("poll_interval must be a non-negative number")
    return float(value)


def _wait_timeout(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("timeout must be a positive number or None")
    if value <= 0:
        raise ValueError("timeout must be a positive number or None")
    return float(value)


def _wait_deadline(expires_at: float, timeout: float | None) -> float:
    if timeout is None:
        return expires_at
    return min(expires_at, time.monotonic() + timeout)


def _required_callback[T](callback: T | None) -> T:
    if callback is None:
        raise ValueError("OAuth flow values are created by Client.connect(..., method='oauth')")
    return callback


def _expired(provider: str) -> ProviderConnectionError:
    return ProviderConnectionError(
        f"OAuth authorization for {provider!r} expired",
        provider=provider,
        code="oauth_authorization_expired",
        permanent=False,
    )


def _wait_expired(provider: str) -> ProviderConnectionError:
    return ProviderConnectionError(
        f"Timed out waiting for OAuth authorization for {provider!r}",
        provider=provider,
        code="oauth_authorization_timeout",
        permanent=False,
    )


def list() -> tuple[Connection, ...]:
    """List connections through the lazy default Client."""

    from screamingface._default_client import default_client

    return default_client().connections.list()


def get(provider: str) -> Connection:
    """Get one connection through the lazy default Client."""

    from screamingface._default_client import default_client

    return default_client().connections.get(provider)


__all__ = [
    "AsyncOAuthFlow",
    "Connection",
    "ConnectionStatus",
    "OAuthFlow",
    "get",
    "list",
]
