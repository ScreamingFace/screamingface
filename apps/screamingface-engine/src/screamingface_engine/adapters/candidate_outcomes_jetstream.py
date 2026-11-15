"""The deployed `CandidateOutcomeStream`: JetStream stream `url4-candidate-outcomes` (OME-1785).

FEATURE: first-class Runs, E5 P1 spec D4 and R11. Workers and the App's terminal writers publish
each Candidate's outcome here; the App's one writer consumes them through a durable pull consumer
with explicit acks, and acks only after its database commit (spec R4).

INVARIANT: a work queue. An acked outcome is removed; an unacked one is delivered again after
`ack_wait_s`, for as long as the stream keeps it (`max_age_s`, 24 h). So a database outage delays
outcomes but loses none, and reconcile's 48 h `lost` cutoff is safely past every redelivery.

LAYERING: a shared leaf, beside `adapters.jetstream`. It never imports the Run registry.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace

import nats
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    DiscardPolicy,
    RetentionPolicy,
    StorageType,
    StreamConfig,
)
from nats.js.errors import APIError, NotFoundError

from screamingface_engine.adapters.jetstream import STREAM_NAME_IN_USE_ERR_CODE
from screamingface_engine.candidate_outcomes import (
    DEFAULT_OUTCOMES_MAX_AGE_S,
    MAX_OUTCOME_BYTES,
    CandidateOutcome,
    OutcomeDelivery,
    decode_outcome,
    encode_outcome,
)

logger = logging.getLogger(__name__)

CANDIDATE_OUTCOMES_STREAM = "url4-candidate-outcomes"
_FETCH_WINDOW_S = 5.0
_FETCH_BATCH = 64


@dataclass(frozen=True)
class CandidateOutcomesStreamConfig:
    """The stream, and the writer's consumer. Defaults are the chart defaults (spec R11).

    WHY 64 MiB: an outcome is ~200 bytes, so this holds hundreds of thousands, far beyond the
    outcomes a 24 h database outage could pile up.
    """

    name: str = CANDIDATE_OUTCOMES_STREAM
    max_age_s: float = DEFAULT_OUTCOMES_MAX_AGE_S
    max_bytes: int = 64 * 1024**2
    replicas: int = 1
    ack_wait_s: float = 30.0

    @property
    def subject(self) -> str:
        return self.name

    @property
    def consumer(self) -> str:
        return f"{self.name}-writer"

    def stream_config(self) -> StreamConfig:
        return StreamConfig(
            name=self.name,
            subjects=[self.subject],
            retention=RetentionPolicy.WORK_QUEUE,
            storage=StorageType.FILE,
            max_age=self.max_age_s,
            max_bytes=self.max_bytes,
            # WHY `NEW`: a full stream refuses the publish, which the runner sees, instead of
            # silently dropping the oldest outcomes that are not written yet.
            discard=DiscardPolicy.NEW,
            max_msg_size=MAX_OUTCOME_BYTES,
            num_replicas=self.replicas,
        )

    def consumer_config(self) -> ConsumerConfig:
        # WHY no `max_deliver`: an outcome is redelivered until it is written or the stream's
        # `max_age` drops it. Giving up sooner would lose an outcome to a database outage.
        return ConsumerConfig(
            durable_name=self.consumer,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=self.ack_wait_s,
        )


# The fields startup applies to a live stream; `retention`, `storage` and `subjects` are fixed.
# WHY not `num_replicas`: no setting configures it, so an operator's own replica count is left
# alone.
_MUTABLE_FIELDS = ("max_age", "max_bytes", "discard", "max_msg_size")
# The limits a caller without `update` may find widened but never narrowed: below this code's, an
# outcome could expire or be refused before it is written (spec R4, R6).
_FLOOR_FIELDS = ("max_age", "max_bytes", "max_msg_size")
_IMMUTABLE_FIELDS = ("retention", "storage", "subjects")


def _check_live_stream(
    name: str, current: StreamConfig, wanted: StreamConfig, *, update: bool
) -> None:
    """Refuse a live stream this code cannot keep outcomes on (spec R4, R6, R11)."""
    # WHY `discard` only without `update`: startup applies it (`_MUTABLE_FIELDS`); any other
    # caller refuses a stream that would drop outcomes not yet written.
    checked = _IMMUTABLE_FIELDS if update else (*_IMMUTABLE_FIELDS, "discard")
    for field in checked:
        if getattr(current, field) != getattr(wanted, field):
            raise CandidateOutcomesStreamConfigError(
                f"stream {name!r}: `{field}` is {getattr(current, field)}, "
                f"expected {getattr(wanted, field)}; outcomes would not be kept until written"
            )
    if update:
        return
    for field in _FLOOR_FIELDS:
        if _narrower(getattr(current, field), getattr(wanted, field)):
            raise CandidateOutcomesStreamConfigError(
                f"stream {name!r}: `{field}` is {getattr(current, field)}, below this "
                f"Engine's {getattr(wanted, field)}; outcomes could be lost before they are written"
            )


def _narrower(current: float | None, wanted: float | None) -> bool:
    """Whether a live limit is below this code's. JetStream reads 0 or -1 as unlimited."""
    if current is None or current <= 0:
        return False
    return wanted is not None and wanted > 0 and current < wanted


class CandidateOutcomesStreamConfigError(RuntimeError):
    """The stream exists with a retention, storage, discard policy or subject this code cannot
    run on. Startup fails."""


class JetStreamCandidateOutcomeStream:
    """`CandidateOutcomeStream` over one lazily opened NATS connection."""

    # INVARIANT (spec R6): an unacked outcome outlives any one process, so reconcile waits out
    # the stream's retention instead of settling a pre-restart Candidate as `lost` at once.
    survives_restart = True

    def __init__(self, nats_url: str, *, config: CandidateOutcomesStreamConfig | None = None):
        self._url = nats_url
        self.config = config if config is not None else CandidateOutcomesStreamConfig()
        self._nc: Client | None = None
        self._js: JetStreamContext | None = None
        self._connect_lock = asyncio.Lock()

    async def _jetstream(self) -> JetStreamContext:
        js = self._js
        if js is not None and self._nc is not None and not self._nc.is_closed:
            return js
        # WHY the lock: publishers run concurrently, and two racing connects would leak one.
        async with self._connect_lock:
            if self._js is None or self._nc is None or self._nc.is_closed:
                self._nc = await nats.connect(self._url)
                self._js = self._nc.jetstream()
            return self._js

    async def ensure_stream(self, *, update: bool = False) -> None:
        """Create the stream if it is missing (spec R11), and check what an existing one is.

        ``update=True`` is for the App and the runner pool at startup: they own the chart's
        `candidateOutcomes.*` values, so a changed limit, and the writer's `ack_wait`, are
        applied. INVARIANT: without it a live stream is never rewritten, so a process built with
        the defaults cannot shrink a stream an operator widened.
        """
        js = await self._jetstream()
        wanted = self.config.stream_config()
        try:
            current = (await js.stream_info(self.config.name)).config
        except NotFoundError:
            try:
                await js.add_stream(wanted)
                current = wanted
            except APIError as exc:
                # WHY: the App and the runner pool declare it at the same startup; when the other
                # created it first, reconcile against what it created.
                if exc.err_code != STREAM_NAME_IN_USE_ERR_CODE:
                    raise
                current = (await js.stream_info(self.config.name)).config
        _check_live_stream(self.config.name, current, wanted, update=update)
        if not update:
            return
        if any(getattr(current, field) != getattr(wanted, field) for field in _MUTABLE_FIELDS):
            # INVARIANT: only the fields startup owns change; everything else on the live stream,
            # an operator's replica count included, is sent back as it is.
            owned = {field: getattr(wanted, field) for field in _MUTABLE_FIELDS}
            await js.update_stream(replace(current, **owned))
            logger.info("stream %s: applied changed limits", self.config.name)
        # WHY here: a durable consumer keeps the config it was created with, so a changed
        # `ack_wait` reaches it only through this explicit update.
        await js.add_consumer(self.config.name, self.config.consumer_config())

    async def publish(self, topic: str, outcome: CandidateOutcome) -> None:
        js = await self._jetstream()
        await js.publish(self.config.subject, encode_outcome(topic, outcome))

    async def consume(self) -> AsyncGenerator[OutcomeDelivery, None]:
        js = await self._jetstream()
        # WHY add first: `pull_subscribe` binds an existing durable as it is, so a changed
        # `ack_wait`, or a durable made by hand with a `max_deliver`, would silently stay. The
        # server updates an existing durable's editable fields, and refuses the rest loudly.
        await js.add_consumer(self.config.name, self.config.consumer_config())
        sub = await js.pull_subscribe(
            self.config.subject,
            durable=self.config.consumer,
            stream=self.config.name,
            config=self.config.consumer_config(),
        )
        try:
            while True:
                try:
                    msgs = await sub.fetch(_FETCH_BATCH, timeout=_FETCH_WINDOW_S)
                except TimeoutError:
                    # An empty stream is a result, not an error: nats-py raises on an empty window.
                    continue
                for msg in msgs:
                    delivery = await self._delivery(msg)
                    if delivery is not None:
                        yield delivery
        finally:
            # WHY: the writer opens a new consumer after a failure; the old subscription goes.
            # Suppressed, so a broker already gone never replaces the error or cancel that ended
            # the consumer.
            with contextlib.suppress(Exception):
                await sub.unsubscribe()

    async def _delivery(self, msg: Msg) -> OutcomeDelivery | None:
        try:
            topic, outcome = decode_outcome(msg.data)
        except ValueError:
            # WHY term, not nak: no writer can ever decode it, and redelivering it forever would
            # only keep it ahead of real outcomes.
            logger.error("dropping a malformed candidate outcome on %s", self.config.name)
            await msg.term()
            return None
        return OutcomeDelivery(topic, outcome, msg.ack)

    async def close(self) -> None:
        if self._nc is not None and not self._nc.is_closed:
            await self._nc.drain()
        self._nc = self._js = None


__all__ = [
    "CANDIDATE_OUTCOMES_STREAM",
    "CandidateOutcomesStreamConfig",
    "CandidateOutcomesStreamConfigError",
    "JetStreamCandidateOutcomeStream",
]
