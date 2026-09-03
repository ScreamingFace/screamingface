from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from url4.streaming.protocol import OutboundFrame


class StreamNotFoundError(LookupError):
    """The topic's stream does not exist — the Run finished and its stream was reclaimed.

    Raised by a consumer's :meth:`EventConsumer.subscribe` ONLY on a resume attach
    (``from_sequence`` set): a fresh attach legitimately precedes the Run's first publish,
    so it may create the stream. A resume cursor with no stream to resume from means the
    Run ended and the reclaim grace elapsed — the client can stop reconnecting (OME-1019).
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
        """Reclaim a topic for good — called once, on the terminal DELETE, never mid-run.

        Distinct from :meth:`purge` because for a broker-backed adapter they are different
        operations with different costs: purging empties a stream but leaves the stream object,
        its consumer state and its on-disk directory behind, so a purge-only teardown still
        accumulates one permanent stream per run. `purge` cannot simply be made to delete —
        `assert_stream_conformance` requires it to leave the sequence counter intact, and a
        recreated stream restarts at 1.

        Defaults to :meth:`purge` so an adapter with nothing broker-side to reclaim (the
        in-process log) needs no override, and so adding this never broke an existing
        implementer. Must be idempotent: a topic that is already gone is success, not an error.
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
