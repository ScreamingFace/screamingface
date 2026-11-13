"""`OutcomeWriter`: the one writer of Candidate outcomes (OME-1785, E5 P1 spec R4).

FEATURE: first-class Runs. Every producer publishes to the `CandidateOutcomeStream`; only this
writer, in the App, calls `RunRegistry.settle`, so every database write stays in the App (spec D3).

INVARIANT (spec R4): a delivery is acked only after its `settle` committed. An outcome whose write
failed is not acked, and the stream delivers it again.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable
from typing import Protocol

from screamingface_engine.candidate_outcomes import CandidateOutcome, CandidateOutcomeStream

logger = logging.getLogger(__name__)

DEFAULT_RETRY_S = 5.0
"""How long the writer waits before consuming again after a failed write or a broken stream."""


class _Settles(Protocol):
    def settle(self, topic: str, outcome: CandidateOutcome) -> Awaitable[None]: ...


class OutcomeWriter:
    def __init__(
        self,
        stream: CandidateOutcomeStream,
        registry: _Settles,
        *,
        retry_s: float = DEFAULT_RETRY_S,
    ) -> None:
        self._stream = stream
        self._registry = registry
        self._retry_s = retry_s

    async def run(self) -> None:
        """Write outcomes until cancelled. A failure restarts the consumer after `retry_s`."""
        while True:
            try:
                await self._write_until_failure()
            except Exception:
                # WHY restart rather than stop: the database or the broker comes back, and a
                # stopped writer would leave every later outcome unwritten until the App restarts.
                logger.exception("the candidate outcome writer failed; consuming again shortly")
            await asyncio.sleep(self._retry_s)

    async def _write_until_failure(self) -> None:
        # WHY aclosing: the failed consumer is closed before a new one starts, so a restart never
        # leaves a subscription behind.
        async with contextlib.aclosing(self._stream.consume()) as deliveries:
            async for delivery in deliveries:
                # An unbound topic settles as a no-op (spec R3) and is acked like any other.
                await self._registry.settle(delivery.topic, delivery.outcome)
                await delivery.ack()


__all__ = ["DEFAULT_RETRY_S", "OutcomeWriter"]
