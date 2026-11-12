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
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass

from screamingface_engine.candidate_outcomes import (
    DEFAULT_OUTCOMES_MAX_AGE_S,
    CandidateOutcome,
    OutcomeDelivery,
    OutcomeNotAccepted,
    check_topic,
)
from screamingface_engine.topic_claims import Claim
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
            # Resume on a topic with no history: the Run finished and its frames were
            # reclaimed (OME-1019). A FRESH attach may create the stream, same as the broker
            # adapter — but the two adapters raise on a DIFFERENT condition, not the same
            # rule: the broker adapter (a shared stream) raises only when the first retained
            # frame is the kept terminal frame (`keep=1`), because an empty subject there is
            # also the state of a queued run. This in-process log never keeps a reclaimed
            # topic's history at all, so it raises whenever the topic has no history —
            # acceptable here because it never reclaims WHILE a resume could race it: it is
            # local-mode only, with no second process to resume from a stream this one just
            # reclaimed.
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


DEFAULT_OUTCOME_ACK_WAIT_S = 30.0
"""How long an unacked outcome waits before it is delivered again, as `url4-candidate-outcomes`."""


DEFAULT_MAX_OUTCOMES = 300_000
"""About what `url4-candidate-outcomes`' 64 MiB holds at ~200 bytes an outcome."""


class OutcomeStreamFull(OutcomeNotAccepted):
    """A publish was refused because the stream holds `max_outcomes` unwritten outcomes."""


# WHY eq=False: two outcomes can carry the same topic and verdict (a duplicate claim), and an ack
# must remove the one delivery it belongs to, so entries compare by identity.
@dataclass(slots=True, eq=False)
class _Outcome:
    topic: str
    outcome: CandidateOutcome
    # The loop time it was published at, for the stream's max age.
    published_at: float = 0.0
    # While delivered and unacked: the loop time after which it is delivered again.
    redeliver_at: float = 0.0


class InMemoryCandidateOutcomeStream:
    """The local-mode `CandidateOutcomeStream` (OME-1785, E5 P1 spec D4).

    Same contract as the JetStream adapter: publish order, explicit acks, and redelivery of an
    outcome not acked within `ack_wait_s`, so the App's writer runs one code path in both modes.

    INVARIANT (spec R6): `survives_restart` is False. Outcomes live in this process only, so a
    restart loses the unacked ones, and reconcile settles their Candidates as `lost`.

    Bounded like the stream: an outcome older than `max_age_s` is dropped, and a publish past
    `max_outcomes` is refused (JetStream's `discard=new`), so an outcome nobody writes cannot
    grow the process without limit.
    """

    survives_restart = False

    def __init__(
        self,
        *,
        ack_wait_s: float = DEFAULT_OUTCOME_ACK_WAIT_S,
        max_age_s: float = DEFAULT_OUTCOMES_MAX_AGE_S,
        max_outcomes: int = DEFAULT_MAX_OUTCOMES,
    ) -> None:
        self._ack_wait_s = ack_wait_s
        self._max_age_s = max_age_s
        self._max_outcomes = max_outcomes
        self._ready: deque[_Outcome] = deque()
        self._unacked: list[_Outcome] = []
        self._changed = asyncio.Condition()

    async def ensure_stream(self, *, update: bool = False) -> None:
        return None

    async def publish(self, topic: str, outcome: CandidateOutcome) -> None:
        # WHY: the JetStream codec refuses the same topics, so the two adapters keep one contract.
        check_topic(topic)
        async with self._changed:
            now = asyncio.get_running_loop().time()
            self._drop_expired(now)
            if len(self._ready) + len(self._unacked) >= self._max_outcomes:
                raise OutcomeStreamFull(f"{self._max_outcomes} outcomes are waiting to be written")
            self._ready.append(_Outcome(topic, outcome, published_at=now))
            self._changed.notify_all()

    def _drop_expired(self, now: float) -> None:
        cutoff = now - self._max_age_s
        self._ready = deque(entry for entry in self._ready if entry.published_at > cutoff)
        self._unacked = [entry for entry in self._unacked if entry.published_at > cutoff]

    async def consume(self) -> AsyncGenerator[OutcomeDelivery, None]:
        while True:
            entry = await self._next()
            yield OutcomeDelivery(entry.topic, entry.outcome, lambda entry=entry: self._ack(entry))

    async def _next(self) -> _Outcome:
        loop = asyncio.get_running_loop()
        async with self._changed:
            while True:
                now = loop.time()
                self._drop_expired(now)
                due = [entry for entry in self._unacked if entry.redeliver_at <= now]
                for entry in due:
                    self._unacked.remove(entry)
                self._ready.extend(due)
                if self._ready:
                    entry = self._ready.popleft()
                    entry.redeliver_at = now + self._ack_wait_s
                    self._unacked.append(entry)
                    return entry
                await self._wait(now)

    async def _wait(self, now: float) -> None:
        """Until something is published, or the next unacked outcome falls due."""
        deadline = min((entry.redeliver_at for entry in self._unacked), default=None)
        timeout = None if deadline is None else max(deadline - now, 0.0)
        try:
            await asyncio.wait_for(self._changed.wait(), timeout)
        except TimeoutError:
            return

    async def _ack(self, entry: _Outcome) -> None:
        async with self._changed:
            if entry in self._unacked:
                self._unacked.remove(entry)


class InMemoryTopicClaims:
    """The `TopicClaims` double (E5 P2 spec D7): the JetStream bucket's contract in one process.

    Each write gets the next revision and expires `max_age_s` after it, as a key-value entry
    does. INVARIANT: no method awaits between its read and its write, so on one event loop each
    is as atomic as the broker's create and compare-and-set.
    """

    def __init__(self, *, max_age_s: float = 86_400.0) -> None:
        self._max_age_s = max_age_s
        self._revision = 0
        # topic -> (the claim, the loop time it was written)
        self._entries: dict[str, tuple[Claim, float]] = {}

    async def ensure_bucket(self, *, update: bool = False) -> None:
        return None

    def _current(self, topic: str) -> Claim | None:
        entry = self._entries.get(topic)
        if entry is None:
            return None
        claim, written_at = entry
        if asyncio.get_running_loop().time() - written_at >= self._max_age_s:
            del self._entries[topic]
            return None
        return claim

    def _write(self, topic: str, holder: str, *, finished: bool) -> Claim:
        self._revision += 1
        claim = Claim(holder, self._revision, finished)
        self._entries[topic] = (claim, asyncio.get_running_loop().time())
        return claim

    async def claim(self, topic: str, worker_id: str) -> Claim:
        current = self._current(topic)
        return current if current is not None else self._write(topic, worker_id, finished=False)

    async def take_over(self, topic: str, worker_id: str, revision: int) -> Claim | None:
        current = self._current(topic)
        if current is None or current.revision != revision:
            return None
        return self._write(topic, worker_id, finished=False)

    async def finish(self, topic: str, worker_id: str) -> None:
        current = self._current(topic)
        if current is not None and current.holder == worker_id and not current.finished:
            self._write(topic, worker_id, finished=True)

    async def close(self) -> None:
        return None


__all__ = [
    "DEFAULT_MAX_FRAMES_PER_TOPIC",
    "DEFAULT_MAX_OUTCOMES",
    "DEFAULT_OUTCOME_ACK_WAIT_S",
    "InMemoryCandidateOutcomeStream",
    "InMemoryEventStream",
    "InMemoryTopicClaims",
    "OutcomeStreamFull",
]
