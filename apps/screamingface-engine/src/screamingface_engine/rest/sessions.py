"""The port ``routes.py`` uses to reach a topic's WebSocket session — its declaration, and its ear.

``start_run`` has to reconcile the cache policy declared on the attach frame with the one on its
own ``Cache-Control`` header (spec §5.3), and then say so when the header overrode the frame. Both
halves are questions about a session the WebSocket transport owns, so they arrive here as a port
rather than as an import of ``ws.registry`` — the same shape, and for the same reason, as
``SubscriberGate`` next door.

The 428 gate is what makes the second half deliverable rather than best-effort: a run cannot be
scheduled unless a subscriber is already attached, so at the moment an override happens there IS a
live connection for the topic in this process. The App never publishes to the broker, so this is
the only route a notice has.
"""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from url4.streaming.protocol import CachePolicy, OutboundFrame


class RunSessions(Protocol):
    """Port for reading a topic's declared cache intent and reaching whoever declared it."""

    def cache_policy_for(self, topic: str) -> CachePolicy | None:
        """The intent standing for ``topic``, or ``None`` when no attach frame declared one."""
        ...

    def notify(self, topic: str, frame: OutboundFrame) -> None:
        """Offer ``frame`` to every connection attached to ``topic``; a silent no-op if none is."""
        ...

    def hold_sync(self, topic: str) -> AbstractAsyncContextManager[None]:
        """Count a waiting sync request as ``topic``'s audience for the block (PRD 02)."""
        ...


__all__ = ["RunSessions"]
