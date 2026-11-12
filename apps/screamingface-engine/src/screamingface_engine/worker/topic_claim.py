"""The claim step of an exclusive start (E5 P2 spec D7, R3).

FEATURE: a detached Run (OME-1837). The Engine's driver sends a start again whenever it cannot
tell whether the first one landed (D6), so two workers can take two copies of one start, minutes
apart, where the cross-pod probe (OME-1089) sees neither: it runs on redeliveries only, and a
repeated start is a fresh message. Before it runs an `exclusive` start, a worker claims the topic
in the `url4-claims` bucket; exactly one claim succeeds and every other copy is acked away.

INVARIANT: two copies both run only when the holder is alive but does not answer in time, when the
bucket is unreachable or slow (the worker then runs, as it does today when it cannot tell), or when
the repeat comes after both the claim and the terminal frame expired.

INVARIANT: a worker answers for a topic only from `claimed`, the topics whose claim it won, from the
win until it marks the claim finished. Never from `_starting`, which holds a topic from the moment
its message is pulled, before any claim.

LAYERING: the worker's. It imports the shared leaves `topic_claims` and `subjects`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from nats.errors import NoRespondersError

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.subjects import claim_subject_for
from screamingface_engine.topic_claims import Claim, TopicClaims, TopicClaimsUnavailable

logger = logging.getLogger(__name__)

ANSWER_TIMEOUT_S = 0.25
"""How long a worker waits for a claim's holder to say it still has the run (R3)."""
DEFAULT_CLAIM_BUDGET_S = 5.0
"""The whole claim step's budget (`topic_claim_budget_s`): well inside the queue's 60 s
`ack_wait`, so a slow bucket never costs the message its delivery."""


class _Ask(Protocol):
    """The slice of a core NATS client that asks a holder (`url4.runclaim.<topic>`)."""

    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any: ...


class ClaimGate:
    """Claims a topic for this worker, and marks its claim finished at the run's end."""

    def __init__(
        self,
        *,
        claims: TopicClaims,
        worker_id: str,
        ask: _Ask | None,
        ended: Callable[[str], Awaitable[bool]],
        claimed: set[str],
        budget_s: float = DEFAULT_CLAIM_BUDGET_S,
        answer_timeout_s: float = ANSWER_TIMEOUT_S,
    ) -> None:
        self._claims = claims
        self._worker_id = worker_id
        self._ask = ask
        # Whether the topic's stream already ends in a terminal frame.
        self._ended = ended
        # Shared with the worker, which answers `url4.runclaim.<topic>` from it.
        self._claimed = claimed
        self._budget_s = budget_s
        self._answer_timeout_s = answer_timeout_s

    async def admit(self, topic: str) -> bool:
        """Whether this copy runs. False: another worker has, or had, the run, and the caller
        acks this copy away."""
        try:
            async with asyncio.timeout(self._budget_s):
                runs = await self._admit(topic)
        except (TopicClaimsUnavailable, TimeoutError) as exc:
            logger.warning(
                "could not claim %s (%r); running it, as when nothing can tell", topic, exc
            )
            return True
        if runs:
            self._claimed.add(topic)
        return runs

    async def _admit(self, topic: str) -> bool:
        claim = await self._claims.claim(topic, self._worker_id)
        while (runs := await self._verdict(topic, claim)) is None:
            # The holder is gone and the run never ended: take its claim over. Of two workers
            # doing so, the compare-and-set lets exactly one through.
            if await self._claims.take_over(topic, self._worker_id, claim.revision) is not None:
                return True
            claim = await self._claims.claim(topic, self._worker_id)
        return runs

    async def _verdict(self, topic: str, claim: Claim) -> bool | None:
        """True: this copy runs. False: another worker has, or had, the run. None: the holder is
        gone and the run never ended."""
        if claim.finished or claim.holder == self._worker_id:
            return not claim.finished
        has_run = await self._holder_answers(topic, claim.holder) or await self._has_ended(topic)
        return False if has_run else None

    async def _holder_answers(self, topic: str, holder: str) -> bool:
        answered = False
        if self._ask is not None:
            try:
                await self._ask.request(
                    claim_subject_for(topic), holder.encode(), timeout=self._answer_timeout_s
                )
                answered = True
            except (TimeoutError, NoRespondersError):
                pass
            except Exception as exc:  # noqa: BLE001 - a broker error is no answer
                logger.warning("asking the holder of %s failed with %r", topic, exc)
        return answered

    async def _has_ended(self, topic: str) -> bool:
        """The second read of the topic's last frame: a holder that published its terminal
        frame but had not yet marked its claim finished."""
        try:
            return await self._ended(topic)
        except QueueReadError:
            return False

    async def finish(self, topic: str) -> None:
        """Mark this worker's claim finished, once the run's terminal frame is published and
        before its message is acked. A failure is logged: the ack must still happen."""
        if topic not in self._claimed:
            return
        self._claimed.discard(topic)
        try:
            async with asyncio.timeout(self._budget_s):
                await self._claims.finish(topic, self._worker_id)
        except (TopicClaimsUnavailable, TimeoutError) as exc:
            logger.warning("could not mark the claim of %s finished: %r", topic, exc)

    def release(self, topic: str) -> None:
        """Stop answering for ``topic`` without marking it finished: its run ended without its
        message being acked, and another worker may take the claim over."""
        self._claimed.discard(topic)


class _Message(Protocol):
    data: bytes
    metadata: Any

    async def ack(self) -> None: ...

    async def in_progress(self) -> None: ...


class FinishingMessage:
    """A claimed message whose ack first marks the claim finished (R3). Every ack after a won
    claim follows the run's terminal frame, so one wrapper covers every way the run can end."""

    def __init__(self, inner: _Message, gate: ClaimGate, topic: str) -> None:
        self._inner = inner
        self._gate = gate
        self._topic = topic
        self.data = inner.data
        self.metadata = inner.metadata
        # The enqueue stamp the expiry check reads (`subjects.ENQUEUED_AT_HEADER`).
        self.headers = getattr(inner, "headers", None)

    async def ack(self) -> None:
        await self._gate.finish(self._topic)
        await self._inner.ack()

    async def in_progress(self) -> None:
        await self._inner.in_progress()


__all__ = ["ANSWER_TIMEOUT_S", "DEFAULT_CLAIM_BUDGET_S", "ClaimGate", "FinishingMessage"]
