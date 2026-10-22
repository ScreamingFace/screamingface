"""The node's data table: plain reads served at a path (spec §5.3.7 collections, B §5.4).

STORY: as a node author I serve a value or a provider at a path, and an expression reads it
as data — no intent, no processor. Split from ``server.py`` by reason to change: the data
table changes with collection serving, not with the node's dispatch.

The mixin is mixed into :class:`~url4.peer.server.Url4Node`, which owns the routing checks
(``_check_routable``, ``_is_eval_path``), ``_eval_path`` and the ``_data`` table it sets up.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, overload

DataCallable = Callable[[], str | Awaitable[str]]
DataProvider = str | DataCallable


@dataclass(frozen=True)
class _DataRoute:
    """A registered data route: its provider plus the optional declared media type."""

    provider: DataProvider
    media_type: str | None = None


class DataRoutes:
    """Registration and lookup of the node's data routes."""

    _data: dict[str, _DataRoute]
    _eval_path: str

    if TYPE_CHECKING:  # WHY: provided by Url4Node; declared here only for the type checker.

        def _check_routable(self, path: str) -> None: ...

        def _is_eval_path(self, path: str) -> bool: ...

    @overload
    def data(
        self, path: str, *, media_type: str | None = None
    ) -> Callable[[DataCallable], DataCallable]: ...

    @overload
    def data(self, path: str, provider: DataProvider, *, media_type: str | None = None) -> None: ...

    def data(
        self, path: str, provider: DataProvider | None = None, *, media_type: str | None = None
    ) -> Callable[[DataCallable], DataCallable] | None:
        """Serve a plain data read at ``path`` — static text, a callable, or a decorator.

        ``node.data("/api/rows", '[…]')`` registers a value directly;
        ``@node.data("/api/rows")`` decorates a provider function. ``media_type``
        declares the route's Content-Type so a collection served here parses by
        its declared type (spec §5.3.7) rather than being sniffed — the node's
        :meth:`fetch_ex` reports it. A path under the eval path raises ``ValueError``.
        """
        self._check_routable(path)
        if self._is_eval_path(path.partition("?")[0]):
            raise ValueError(f"data route {path!r} is under the eval path {self._eval_path!r}")
        if provider is not None:
            self._data[path] = _DataRoute(provider, media_type)
            return None

        def register(fn: DataCallable) -> DataCallable:
            self._data[path] = _DataRoute(fn, media_type)
            return fn

        return register

    def has_data(self, path: str) -> bool:
        """Whether a data route is registered at exactly ``path``."""
        return path in self._data
