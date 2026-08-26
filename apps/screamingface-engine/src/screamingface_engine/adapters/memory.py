"""In-process `EventStream` adapter — the local-mode substitute for the JetStream pair.

Same port, same observable semantics (1-based sequence numbers, replay-from-sequence,
purge), no broker: the log is a dict of per-topic lists and readers wake on an
`asyncio.Condition`. This is what makes `--local` a real deployment rather than a
mock — the REST sync-hold and the WS pump both subscribe to it exactly as they
subscribe to `JetStreamConsumer`.

It also remains the fake the test suite runs against (re-exported by
`screamingface_engine.testing`), which is the reason for the parity note below.

# AIDEV-NOTE: keep this in behavioral parity with `JetStreamConsumer`/`JetStreamPublisher` for
# anything callers rely on (sequence numbering, replay-from, purge) — it is the read side most of
# the suite runs against, so drift here hides real adapter bugs.
"""

import asyncio
from bisect import bisect_left
from collections.abc import AsyncIterator

from url4.streaming.codec import decode, encode
from url4.streaming.interfaces import EventStream, StreamNotFoundError, validate_from_sequence
from url4.streaming.protocol import OutboundFrame

DEFAULT_MAX_FRAMES_PER_TOPIC = 10_000
"""Retention bound per topic. JetStream reclaims by its own limits policy; this dict has no
reaper, so a long-lived local server would otherwise grow without bound for as long as it runs."""


def _sequence_of(entry: tuple[int, bytes]) -> int:
    return entry[0]


class InMemoryEventStream(EventStream):
    """A per-topic, append-only in-process log with condition-variable-based waiting.

    Sequence numbers are 1-based and monotonic per topic, and keep counting across a `purge` —
    they identify a position in the topic's history, not an offset into whatever is currently
    retained, so a cursor is never silently re-pointed at different frames.
    """

    def __init__(self, *, max_frames_per_topic: int = DEFAULT_MAX_FRAMES_PER_TOPIC) -> None:
        if max_frames_per_topic < 1:
            raise ValueError(f"max_frames_per_topic must be >= 1, got {max_frames_per_topic}")
        self._log: dict[str, list[tuple[int, bytes]]] = {}
        self._next_seq: dict[str, int] = {}
        self._conds: dict[str, asyncio.Condition] = {}
        self._max_frames = max_frames_per_topic

    async def ensure_stream(self, topic: str) -> None:
        if topic not in self._log:
            self._log[topic] = []
            self._next_seq[topic] = 1
            self._conds[topic] = asyncio.Condition()

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        await self.ensure_stream(topic)
        cond = self._conds[topic]
        async with cond:
            seq = self._next_seq[topic]
            self._next_seq[topic] = seq + 1
            log = self._log[topic]
            log.append((seq, encode(event)))
            # WHY drop the oldest rather than refuse the newest: this mirrors a JetStream limits
            # policy. A subscriber whose cursor has fallen off the front resumes at the earliest
            # RETAINED frame — the same thing it would see against a real stream that rolled over.
            if len(log) > self._max_frames:
                del log[: len(log) - self._max_frames]
            cond.notify_all()

    async def subscribe(
        self, topic: str, from_sequence: int | None = None
    ) -> AsyncIterator[OutboundFrame]:
        """Yields events for `topic` from `from_sequence` (or the start), then blocks and keeps
        yielding as new events are published — never terminates on its own."""
        validate_from_sequence(from_sequence)
        if from_sequence is not None and topic not in self._log:
            # Resume on a topic with no history: the Run finished and the stream was
            # reclaimed (OME-1019). A FRESH attach may create the stream — the same rule
            # as the broker adapter, mirrored for behavioral parity.
            raise StreamNotFoundError(topic)
        await self.ensure_stream(topic)
        cond = self._conds[topic]
        cursor = 1 if from_sequence is None else from_sequence
        while True:
            async with cond:
                log = self._log[topic]
                ready = log[bisect_left(log, cursor, key=_sequence_of) :]
                if not ready:
                    await cond.wait()
                    continue
            for seq, payload in ready:
                cursor = seq + 1
                yield decode(payload, sequence=seq)

    async def purge(self, topic: str) -> None:
        await self.ensure_stream(topic)
        cond = self._conds[topic]
        async with cond:
            self._log[topic] = []


__all__ = ["DEFAULT_MAX_FRAMES_PER_TOPIC", "InMemoryEventStream"]
