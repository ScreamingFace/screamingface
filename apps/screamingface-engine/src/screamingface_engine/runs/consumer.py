"""`OutcomeWriter`: the one writer of Candidate outcomes (OME-1785, E5 P1 spec R4).

FEATURE: first-class Runs. Every producer publishes to the `CandidateOutcomeStream`; only this
writer, in the App, calls `RunRegistry.settle`, so every database write stays in the App (spec D3).

INVARIANT (spec R4): a delivery is acked only after its `settle` committed. An outcome whose write
failed is tried again in place, then, if it still fails, left unacked for the stream to deliver
again.
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
"""How long the writer waits before writing an outcome again, or consuming again after a broken
stream."""
IN_PLACE_TRIES = 12
"""How many times the writer tries one outcome before it consumes again (about a minute at the
default `retry_s`)."""


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
                await self._settle(delivery.topic, delivery.outcome)
                await delivery.ack()

    async def _settle(self, topic: str, outcome: CandidateOutcome) -> None:
        """Write one outcome, trying it again in place before the consumer moves on.

        WHY in place (#1759 review): a restarted consumer gets the later outcomes at once and
        this one only after the stream's `ack_wait`, so a later outcome of the same topic could
        commit first, and a Candidate's state is first-wins. WHY bounded: an outcome that can
        never be written must not hold every other one back; past `IN_PLACE_TRIES` the consumer
        restarts, as before.
        """
        for tries_left in range(IN_PLACE_TRIES - 1, -1, -1):
            try:
                await self._registry.settle(topic, outcome)
                return
            except Exception:
                if not tries_left:
                    raise
                logger.warning(
                    "could not write the outcome of %s; trying it again", topic, exc_info=True
                )
                await asyncio.sleep(self._retry_s)


__all__ = ["DEFAULT_RETRY_S", "IN_PLACE_TRIES", "OutcomeWriter"]
