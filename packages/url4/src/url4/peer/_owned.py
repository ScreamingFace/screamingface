"""Lazy ownership of an io adapter, shared by the two peer facades.

:class:`~url4.peer.client.Client` and :class:`~url4.peer.server.Url4Node` both
take an optional injected :class:`~url4.io.layer.IOLayer` and, when none is
given, create — and then own — an :class:`~url4.io.http.HttpIOLayer`. That
injected-versus-owned lifecycle lives here once, by composition rather than
inheritance: each facade keeps its own public surface and delegates only the
lazy accessor, the close, and the async-context exit.
"""

from __future__ import annotations

from url4.io.layer import IOLayer, SupportsClose


def _http_io() -> IOLayer:
    from url4.io.http import HttpIOLayer  # composition root: lazy transport import

    return HttpIOLayer()


class _OwnedIO:
    """An injected io layer plus a lazily-created owned one.

    :meth:`outbound` returns the injected layer when one was given, else creates
    (once) and returns the owned adapter. :meth:`aclose` closes ONLY the owned
    adapter — an injected layer is the caller's to manage — and is idempotent,
    because the reference is dropped before the close is awaited.
    """

    def __init__(self, injected: IOLayer | None) -> None:
        self._injected = injected
        self._owned: IOLayer | None = None

    def outbound(self) -> IOLayer:
        """The injected adapter, else the owned one created on first use."""
        if self._injected is not None:
            return self._injected
        if self._owned is None:
            self._owned = _http_io()
        return self._owned

    async def aclose(self) -> None:
        """Close the owned adapter if one exists; leave an injected layer alone."""
        owned, self._owned = self._owned, None
        if isinstance(owned, SupportsClose):
            await owned.aclose()

    async def __aenter__(self) -> _OwnedIO:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
