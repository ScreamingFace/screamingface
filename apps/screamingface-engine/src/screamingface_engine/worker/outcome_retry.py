"""A driver-started run's outcome, published again until the stream takes it (E5 P2 spec R6).

FEATURE: a detached Run (OME-1837). A Candidate whose outcome is lost stays `scheduled` until
reconcile settles it `lost` 48 h later, holding one of its Run's 8 slots. For a run the Engine's
driver started, the worker retries a publish the stream refused because its broker was unreachable
or it was full (`OutcomeNotAccepted`), with backoff, until it lands or the worker drains. Any other
refusal is logged and dropped, as before.

INVARIANT: a retry is a task of its own, apart from the run's queue message, which is acked as
before, so it holds no worker slot. The drain awaits it.

LAYERING: the worker's.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Protocol

from screamingface_engine.candidate_outcomes import CandidateOutcome, OutcomeNotAccepted

logger = logging.getLogger(__name__)

FIRST_DELAY_S = 1.0
MAX_DELAY_S = 30.0


class _Publishes(Protocol):
    async def publish(self, topic: str, outcome: CandidateOutcome) -> None: ...


class OutcomeRetries:
    """Publishes outcomes, retrying the ones the stream could not take now."""

    def __init__(
        self,
        stream: _Publishes,
        *,
        first_delay_s: float = FIRST_DELAY_S,
        max_delay_s: float = MAX_DELAY_S,
    ) -> None:
        self._stream = stream
        self._first_delay_s = first_delay_s
        self._max_delay_s = max_delay_s
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopped = asyncio.Event()

    @property
    def pending(self) -> int:
        """How many outcomes are still being retried."""
        return len(self._tasks)

    async def publish(self, topic: str, outcome: CandidateOutcome) -> None:
        """Publish ``outcome`` now; if the stream cannot take it now, keep trying apart."""
        try:
            await self._stream.publish(topic, outcome)
        except OutcomeNotAccepted as exc:
            logger.warning("the outcome of %s was not taken (%r); retrying it", topic, exc)
            task = asyncio.create_task(self._retry(topic, outcome))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except Exception:
            logger.exception("could not publish the candidate outcome of %s", topic)

    async def _retry(self, topic: str, outcome: CandidateOutcome) -> None:
        delay = self._first_delay_s
        while not await self._stopped_within(delay):
            try:
                await self._stream.publish(topic, outcome)
            except OutcomeNotAccepted:
                delay = min(delay * 2, self._max_delay_s)
                continue
            except Exception:
                logger.exception("could not publish the candidate outcome of %s", topic)
            return
        logger.error("the outcome of %s was not published before the worker stopped", topic)

    async def _stopped_within(self, delay_s: float) -> bool:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopped.wait(), delay_s)
        return self._stopped.is_set()

    async def drain(self, grace_s: float) -> None:
        """Give the retries up to ``grace_s`` to land, then stop the rest: the worker exits."""
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=max(grace_s, 0))
        self._stopped.set()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


__all__ = ["OutcomeRetries"]
