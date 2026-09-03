"""Authentication interface consumed by HTTP and WebSocket transports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping

import httpx


class _TransportAuth(httpx.Auth, ABC):
    """Credentials propagated through HTTP and optional WebSocket transports."""

    requires_request_body = True

    @abstractmethod
    def reauthenticate(self, *, timeout: float = 300.0) -> None: ...

    @abstractmethod
    async def reauthenticate_async(self, *, timeout: float = 300.0) -> None: ...

    @abstractmethod
    def websocket_headers(self) -> Mapping[str, str]: ...

    @abstractmethod
    async def websocket_headers_async(self) -> Mapping[str, str]: ...

    @abstractmethod
    def close(self) -> None: ...


class _ClientAuth(_TransportAuth, ABC):
    """Authentication lifecycle owned by the public sync and async Clients."""

    @property
    @abstractmethod
    def authenticated(self) -> bool: ...

    @property
    @abstractmethod
    def authenticating(self) -> bool: ...

    @abstractmethod
    def login(self, *, timeout: float = 300.0) -> None: ...

    @abstractmethod
    async def login_async(self, *, timeout: float = 300.0) -> None: ...

    @abstractmethod
    def subscribe_authorization(self, presenter: Callable[[str], None]) -> Callable[[], None]: ...

    @abstractmethod
    def cancel_login(self) -> None: ...

    @abstractmethod
    def access_required(self) -> bool: ...

    @abstractmethod
    def logout(self) -> None: ...

    @abstractmethod
    async def logout_async(self) -> None: ...


__all__: list[str] = []
