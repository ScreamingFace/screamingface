from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from url4.streaming.protocol import OutboundFrame


class StreamNotFoundError(LookupError):
    """Raised on a resume whose frames were reclaimed after the Run ended.

    Raised by a consumer's :meth:`EventConsumer.subscribe` ONLY on a resume attach
    (``from_sequence`` set): a fresh attach legitimately precedes the Run's first publish,
    so it may create the stream. A resume cursor with nothing to resume from means the Run
    ended and its frames were reclaimed — the client can stop reconnecting (OME-1019).
    """


class EventPublisher(ABC):
    @abstractmethod
    async def ensure_stream(self, topic: str) -> None:
        pass

    @abstractmethod
    async def publish(self, topic: str, event: OutboundFrame) -> None:
        """Hand one frame to the transport.

        The frames reach the broker in CALL ORDER. An adapter MAY defer the durability
        acknowledgement to :meth:`flush` — so a return from here means "accepted, in
        order", not yet "durable".

        INVARIANT: exactly ONE task calls this per topic. A deferring adapter can only
        order the writes it performs itself, and the consumer finds gaps by the sequence
        the broker assigns from that order, so concurrent callers void both guarantees.

        Raises when a PREVIOUSLY deferred publish has since failed, so a broken transport
        stops a run promptly instead of after the whole in-flight window drains.
        """

    async def flush(self) -> None:
        """Wait until every frame published so far is durable.

        Raises the first deferred failure, then DISCARDS the remaining deferred state, so
        the termination path's own flush does not re-raise an error already reported —
        every exit from a run must still get its terminal frame out.

        Does nothing by default: an adapter whose :meth:`publish` is already durable when
        it returns has nothing to wait for. Only a DEFERRING adapter overrides this, which
        is why this is not abstract — making it so would break every in-process adapter
        and test fake to serve one broker-backed implementation.
        """
        return None

    async def close(self) -> None:
        pass


class EventConsumer(ABC):
    @abstractmethod
    async def ensure_stream(self, topic: str) -> None:
        pass

    @abstractmethod
    def subscribe(
        self, topic: str, from_sequence: int | None = None
    ) -> AsyncIterator[OutboundFrame]:
        pass

    @abstractmethod
    async def purge(self, topic: str) -> None:
        pass

    async def delete_stream(self, topic: str) -> None:
        """Reclaim a finished Run's frames for good — called once, on the terminal DELETE,
        never mid-run.

        The reclaim frees the frames of a Run that has ended; it MUST NOT rewind the topic's
        sequence counter (`assert_stream_conformance`'s `_reclaim_keeps_counting` is the
        contract check) — a topic that is reused, or resumed against, must keep counting from
        where it left off. A broker-backed adapter MAY keep the terminal frame as the evidence
        that the Run is over (see the JetStream adapter's own `delete_stream`, which purges with
        `keep=1`); an adapter with nothing to keep as evidence is free to discard everything.

        Defaults to :meth:`purge` — no evidence kept — which is what an in-process log needs:
        it never reclaims WHILE a resume could still race it (local mode only), so there is
        nothing for a kept frame to guard against. Must be idempotent: a topic that is already
        gone is success, not an error.
        """
        await self.purge(topic)

    async def close(self) -> None:
        pass


class EventStream(EventPublisher, EventConsumer, ABC):
    pass


def validate_from_sequence(from_sequence: int | None) -> None:
    if from_sequence is not None and from_sequence < 1:
        raise ValueError(
            f"from_sequence must be >= 1 (1-based stream sequence), got {from_sequence}"
        )


__all__ = [
    "EventConsumer",
    "EventPublisher",
    "EventStream",
    "StreamNotFoundError",
    "validate_from_sequence",
]
