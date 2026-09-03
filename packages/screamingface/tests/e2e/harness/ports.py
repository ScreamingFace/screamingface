"""The one seam between the e2e stack and whatever answers model calls (OME-961).

Mental model: the engine does not know it is being replayed to. It receives ONE string —
an AI Gateway base URL — and everything behind that URL is an interchangeable backend:
the cache-seeded real gateway (this ticket, ``cache_seeded.CacheSeededGateway``) or the
failure-injecting FakeGateway (sibling ticket OME-962). Adapters never import each other;
they only promise this Protocol.

INVARIANT: the interface is exactly ``start() -> base_url`` and ``stop()``. Growing it
(health hooks, seeding methods, introspection) would couple the engine boot to one
backend's internals — resist; put backend-specific setup in the backend's constructor.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ReplayBackend(Protocol):
    """Anything that can stand where the AI Gateway stands, for one test's lifetime."""

    async def start(self) -> str:
        """Bring the backend up and return its base URL (e.g. ``http://127.0.0.1:49321``).

        Returns:
            The HTTP base URL the engine should be pointed at. The string is the WHOLE
            contract — the caller learns nothing else about the backend.
        """
        ...

    async def stop(self) -> None:
        """Tear the backend down; idempotent, and safe to call after a failed start."""
        ...
