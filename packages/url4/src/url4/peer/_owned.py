"""Lazy ownership of an io adapter, shared by the two peer facades.

:class:`~url4.peer.client.Client` and :class:`~url4.peer.server.Url4Node` both
take an optional injected :class:`~url4.io.layer.IOLayer` and, when none is
given, create — and then own — an :class:`~url4.io.http.HttpIOLayer`. That
injected-versus-owned lifecycle lives here once, by composition rather than
inheritance: each facade keeps its own public surface and delegates only the
lazy accessor, the close, and the async-context exit.
"""

from __future__ import annotations

from url4.io.close_once import CloseOnce
from url4.io.layer import IOLayer, SupportsClose


def _http_io() -> IOLayer:
    from url4.io.http import HttpIOLayer  # composition root: lazy transport import

    return HttpIOLayer()


class _OwnedIO:
    """An injected io layer plus a lazily-created owned one.

    :meth:`outbound` returns the injected layer when one was given, else creates
    (once) and returns the owned adapter. :meth:`aclose` closes ONLY the owned
    adapter — an injected layer is the caller's to manage — and is idempotent:
    the close runs once, and a concurrent or retried call (even after a cancelled
    one) awaits that same close (:class:`~url4.io.close_once.CloseOnce`). Closing is
    final for the owned adapter: after :meth:`aclose`, :meth:`outbound` raises
    instead of creating a new one.
    """

    def __init__(self, injected: IOLayer | None) -> None:
        self._injected = injected
        self._owned: IOLayer | None = None
        self._closed = False
        self._closer = CloseOnce()

    def outbound(self) -> IOLayer:
        """The injected adapter, else the owned one created on first use."""
        if self._injected is not None:
            return self._injected
        if self._closed:
            raise RuntimeError(
                "this Client or Url4Node is closed (its owned IO adapter was closed)"
            )
        if self._owned is None:
            self._owned = _http_io()
        return self._owned

    async def aclose(self) -> None:
        """Close the owned adapter if one exists; leave an injected layer alone."""
        self._closed = True
        # INVARIANT (PR #1555 review 4): dropped only after its close ends, so a retry of a
        # cancelled Client/Url4Node shutdown still reports the adapter's close failure.
        await self._closer.run(self._close_owned)

    async def _close_owned(self) -> None:
        try:
            if isinstance(self._owned, SupportsClose):
                await self._owned.aclose()
        finally:
            self._owned = None

    async def __aenter__(self) -> _OwnedIO:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
