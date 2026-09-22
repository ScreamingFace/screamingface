"""The evaluation scope chain — an immutable parent-pointer :class:`Context`.

Binding resolution in url4 is read-heavy and write-light (a handful of bindings
per expression, read by many ``$name`` lookups) and the chain is shallow (outer
/ iteration / fan-out / reducer). A parent-pointer chain fits that shape: every
:meth:`~Context.child` returns a *new* frame stacked on its parent, so
concurrent iterations never corrupt one another and nested expressions' bindings
never leak outward.

Immutability note: ``frozen=True`` freezes the *field binding*, not the contents
of the ``bindings`` dict. The invariant "never mutate; only ``child()``" is what
makes a ``Context`` effectively immutable — so it is intentionally not advertised
as value-hashable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from url4.core.errors import ScopeError


@dataclass(frozen=True)
class Context:
    """A single frame in the url4 scope chain."""

    bindings: dict[str, Any] = field(default_factory=dict)
    parent: Context | None = None

    def lookup(self, name: str) -> Any:
        """Return the nearest binding for ``name``; raise :class:`ScopeError` if unbound."""
        frame: Context | None = self
        while frame is not None:
            if name in frame.bindings:
                return frame.bindings[name]
            frame = frame.parent
        raise ScopeError(f"unbound url4 reference: ${name}")

    def get(self, name: str, default: Any = None) -> Any:
        """Return the nearest binding for ``name``, or ``default`` if unbound.

        The non-throwing twin of :meth:`lookup` for a name that is normally
        absent — asking "is this binding present?" must not build and catch an
        exception on the common miss path.
        """
        frame: Context | None = self
        while frame is not None:
            if name in frame.bindings:
                return frame.bindings[name]
            frame = frame.parent
        return default

    def child(self, **bindings: Any) -> Context:
        """Return a child frame carrying ``bindings``, with ``self`` as parent."""
        return Context(bindings=dict(bindings), parent=self)

    @classmethod
    def root(cls) -> Context:
        """A fresh, empty root frame."""
        return cls()


__all__ = ["Context"]
