"""The max-deliveries advisory subscriber (OME-1090): a run the queue gave up on gets a
named terminal failure on its own event stream.

JetStream publishes `$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.<stream>.<consumer>`
when a queue message has been redelivered `max_deliver` times without an ack — the queue
gave up on the run. The App subscribes, decodes the run's topic from the advisory's
embedded message (the same env-mapping codec the queue carries), and publishes
`Terminated(failed)` to the run's stream, so the run's status derivation reads that frame
like any other terminal outcome instead of a silent disappearance.

LAYERING: a shared leaf — it imports only the shared leaves (`adapters.jetstream`,
`runner_queue`) and the broker client, so both the control plane and the worker half may
import it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import nats
from nats.aio.client import Client

from screamingface_engine.adapters.jetstream import JetStreamPublisher, QueueReadError
from screamingface_engine.runner_queue import topic_of_message
from screamingface_engine.subjects import RUN_QUEUE_STREAM
from url4.streaming.protocol import (
    ErrorInfo,
    TerminatedData,
    TerminatedEvent,
    source_for,
)

logger = logging.getLogger(__name__)


def advisory_subject_for(stream: str) -> str:
    """The max-deliveries advisory subject for one queue stream's durable consumers.

    Advisories are broker-published on ``$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.
    <stream>.<consumer>``, so the stream token follows the CONFIGURED queue name — a
    subscription built on a hardcoded stream matches nothing the moment an operator
    renames the queue, and every run the queue gives up on ends without a terminal
    frame (review follow-up P2-4).
    """
    return f"$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.{stream}.*"


# The advisor's default subject: the default queue stream. The stream token is wildcarded
# for the CONSUMER — a consumer is `url4-runners-<bucket>`, ONE token (dashes are not NATS
# separators), so `.*` matches it while `.url4-runners.*` would demand a second token and
# match nothing.
MAX_DELIVERIES_ADVISORY_SUBJECT = advisory_subject_for(RUN_QUEUE_STREAM)
# The named failure code on the frame the advisor publishes: the queue gave up on the run.
MAX_DELIVERIES = "max_deliveries"
# How long the subscription loop waits before retrying after a connection failure.
RETRY_DELAY_S = 5.0


def topic_of_advisory(payload: bytes) -> str | None:
    """The run's topic from a max-deliveries advisory; None when unreadable.

    The advisory's `message.data` is the original queue message's body, base64-encoded —
    the same env mapping `encode_message` wrote — so the topic is read through the queue's
    own codec, the single source of truth for what a message describes.
    """
    try:
        advisory = json.loads(payload.decode("utf-8"))
        raw = base64.b64decode(advisory["message"]["data"])
        return topic_of_message(raw)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


class MaxDeliveriesAdvisor:
    """Subscribes to the max-deliveries advisory and publishes a named terminal failure
    for each run the queue gave up on.

    The subscription is a background task on the App's event loop; a dropped connection is
    logged and retried, so a broker blip never silently stops the advisor. The publisher
    and the core connection are this object's own, closed by `aclose` at shutdown.
    """

    def __init__(
        self,
        nats_url: str,
        *,
        run_queue_stream: str = RUN_QUEUE_STREAM,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._url = nats_url
        self._run_queue_stream = run_queue_stream
        # The advisory subject follows the CONFIGURED stream name (review follow-up P2-4):
        # a renamed queue publishes advisories on a different subject, and a subscription
        # on the default would silently stop hearing every max-deliveries event.
        self._subject = advisory_subject_for(run_queue_stream)
        self._clock = clock if clock is not None else (lambda: datetime.now(UTC))
        self._nc: Client | None = None
        self._publisher: JetStreamPublisher | None = None
        # The max-deliveries advisories handled (OME-1092): the /metrics collector's input.
        self.advisories_total = 0

    async def run(self) -> None:
        """Serve the advisory subscription for the process's lifetime, retrying failures.

        WHY close and sleep on EVERY iteration (review follow-up P2-5): a dropped
        subscription ends its `async for` NORMALLY — `_serve` returns without raising —
        so a closed connection is only distinguishable from a healthy long-running one by
        the fact that `_serve` returned. Retrying without closing leaked the previous
        publisher's own lazy NATS connection, and without sleeping, a subscription that
        died immediately reconnected in a hot loop.
        """
        while True:
            try:
                await self._serve()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "max-deliveries advisory subscription failed; retrying in %.0fs",
                    RETRY_DELAY_S,
                )
            finally:
                # Runs on the normal-return (disconnect) path too, so the nc/publisher
                # pair of a dead iteration is always closed before the next connects.
                await self.aclose()
            await asyncio.sleep(RETRY_DELAY_S)

    async def _serve(self) -> None:
        """Connect, subscribe, and forward every advisory to `_handle`."""
        nc = await nats.connect(self._url)
        self._nc = nc
        publisher = JetStreamPublisher(self._url, run_queue_stream=self._run_queue_stream)
        self._publisher = publisher
        sub = await nc.subscribe(self._subject)
        async for msg in sub.messages:
            await self._handle(publisher, msg.data)

    async def _handle(self, publisher: Any, payload: bytes) -> None:
        """Publish the named terminal failure for one advisory, if it decodes."""
        topic = topic_of_advisory(payload)
        if topic is None:
            return
        self.advisories_total += 1
        await self._publish_failure(publisher, topic)

    async def _publish_failure(self, publisher: Any, topic: str) -> None:
        """Publish `Terminated(failed, max_deliveries)` to the run's stream — only if the
        stream does not already end in a terminal frame.

        The frame is a root frame (``source`` is the run's own), so a client attached to
        the run sees it as the run's outcome, exactly like the worker's own terminal
        frames.

        WHY the terminal check first (review follow-up): the advisory and the run race.
        A worker on its FINAL redelivery can complete and publish `Terminated(succeeded)`
        right as the expired `ack_wait` fires this advisory — the run finished, the
        broker merely did not see the ack in time. Publishing unconditionally appended
        `failed` AFTER the success, and `status()` — a last-frame read — reported a
        succeeded run as failed. The check reads the tail like every other terminal
        writer here (`supervisor._publish_if_needed`, `queue_runner.stop`) so the FIRST
        real outcome stands. An UNREADABLE tail is not "no frame" — it skips (logged)
        rather than gambling a failure frame onto a possibly-finished run.
        """
        try:
            last = await publisher.last_frame(topic)
        except QueueReadError:
            logger.warning("max-deliveries advisory for %s skipped: stream tail unreadable", topic)
            return
        if isinstance(last, TerminatedEvent):
            return
        await publisher.ensure_stream(topic)
        await publisher.publish(
            topic,
            TerminatedEvent(
                id=uuid.uuid4().hex,
                source=source_for(topic),
                subject=topic,
                time=self._clock(),
                data=TerminatedData(
                    status="failed",
                    error=ErrorInfo(
                        code=MAX_DELIVERIES,
                        message="the queue gave up on this run after max_deliver attempts",
                    ),
                ),
            ),
        )
        await publisher.flush()

    async def aclose(self) -> None:
        """Close the publisher and the core connection."""
        if self._publisher is not None:
            await self._publisher.close()
            self._publisher = None
        if self._nc is not None:
            await self._nc.close()
            self._nc = None


__all__ = [
    "MAX_DELIVERIES",
    "MAX_DELIVERIES_ADVISORY_SUBJECT",
    "MaxDeliveriesAdvisor",
    "RETRY_DELAY_S",
    "advisory_subject_for",
    "topic_of_advisory",
]
