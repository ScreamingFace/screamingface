"""The durable run queue (OME-1088): the substrate OME-1086's fixed worker pool pulls from.

One JetStream stream (`url4-runq`, `retention=WorkQueue`, file storage) holds every
accepted-but-not-yet-started run; its replica count is configuration, not a constant — see
`QUEUE_REPLICAS`. Publishing sets `Nats-Msg-Id` to the run's topic, so the
broker deduplicates a retried submission within `duplicate_window` — the queue's
`JobAlreadyExists` equivalent, with no lookup table. A durable PULL consumer (`url4-runners`)
with EXPLICIT acks hands messages to workers; an unacked message is redelivered after
`ack_wait`, up to `max_deliver` times, so a worker that dies mid-run loses the run's PROGRESS,
never the run itself.

LAYERING: this module is imported by BOTH the serving half (which publishes) and the future
worker half (which pulls), so it imports nothing from the run half — only the shared leaves
(`job_env`, `subjects`, `adapters.jetstream`) and the broker client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import nats
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.api import AckPolicy, ConsumerConfig, RetentionPolicy, StorageType
from nats.js.errors import BadRequestError

from screamingface_engine import job_env, subjects
from url4.streaming.protocol import CachePolicy
from url4.streaming.trace import valid_traceparent

logger = logging.getLogger(__name__)

# The queue is a SINGLETON — one stream for every run, unlike the per-run event streams — so
# its properties are constants here rather than per-topic derivations.
#
# WHY 1 and not the spec's 3 (owner decision, 2026-09-03): a single-node broker refuses
# `replicas > 1` outright with `ServerError 10074`, and single-node is what the chart's own
# bundled NATS subchart ships, what local dev runs, and what the CI conformance job runs. That
# error is not a `BadRequestError`, so `ensure_stream` does not tolerate it — it escapes into
# the worker's claim loop, which logs and retries forever while every run is refused. A default
# that cannot declare its own stream on the broker the chart bundles is the wrong default.
#
# The durability this gives up is smaller than it looks: the per-run event streams are already
# declared at JetStream's default of one replica (`adapters/jetstream.py`), so a 3-replica queue
# on an otherwise 1-replica bus hardened only the queued-not-started window. Clustering — and
# with it a defensible multi-replica posture for BOTH stream families — is OME-1093's scope;
# raising this is a `run_queue_replicas` setting away, no code change.
QUEUE_REPLICAS = 1
QUEUE_CONSUMER = "url4-runners"
DEFAULT_DUPLICATE_WINDOW_S = 120.0
DEFAULT_QUEUE_MAX_AGE_S = 86_400.0
DEFAULT_ACK_WAIT_S = 60.0
DEFAULT_MAX_DELIVER = 2
DEFAULT_WORKER_SLOTS = 4
# WHY fleet-sized and not `replicas × slots`: `max_ack_pending` is a WHOLE-CONSUMER bound —
# the total unacked messages the one durable consumer may hand out across EVERY puller in the
# fleet — not a per-worker limit. Deriving it from the stream's data-redundancy replica count
# conflated two unrelated numbers and silently capped the whole fleet at 12 in-flight runs.
# The default is sized for a fleet (32 pods × 8 slots, with headroom); deployments that size
# differently must set `run_queue_max_ack_pending` to their fleet's true concurrency. NOTE:
# the value binds when the consumer is CREATED — `pull_subscribe` is idempotent on existence,
# not on config, so changing it on a running queue means deleting and recreating the consumer.
DEFAULT_MAX_ACK_PENDING = 256
DEFAULT_DEPTH_CEILING = 10_000
DEFAULT_IO_CONCURRENCY = 4
DEFAULT_STATE_CACHE_TTL_S = 2.0


def _work_queue_consumer_config(
    *, ack_wait_s: float, max_deliver: int, max_ack_pending: int
) -> ConsumerConfig:
    """The durable PULL consumer's config: EXPLICIT acks with bounded redelivery.

    The opposite of the event streams' broadcast replay config (`AckPolicy.NONE`,
    `adapters.jetstream._broadcast_consumer_config`) in every way that matters: the queue's
    consumer is a WORKER, not a replay reader — it acks each message once it is processed, and
    a worker that dies mid-run must get the message redelivered (`max_deliver`) rather than
    silently lost. `max_ack_pending` bounds how many unacked messages one worker may hold,
    which is what lets several workers share one durable consumer without one hoarding the
    queue.
    """
    return ConsumerConfig(
        ack_policy=AckPolicy.EXPLICIT,
        max_deliver=max_deliver,
        ack_wait=ack_wait_s,
        max_ack_pending=max_ack_pending,
    )


# --- the message codec: ONE encoding, through `job_env` --------------------------------------
# The message body is exactly the per-run env mapping `K8sJobRunner._env` writes onto a Job.
# Both sides render through `job_env`'s renderers, so there is no second encoding to drift;
# `test_run_queue_codec.py` pins the two mappings identical.


def _env_mapping(
    topic: str,
    url4: str,
    deadline_s: int,
    *,
    traceparent: str | None = None,
    profile: str | None = None,
    identity: Mapping[str, str] | None = None,
    cache: CachePolicy | None = None,
    io_concurrency: int = DEFAULT_IO_CONCURRENCY,
    extra_models: Sequence[str] = (),
) -> dict[str, str]:
    """The per-run env mapping a queue message carries, keyed by env name.

    Mirrors `K8sJobRunner._env` entry for entry: the same constants, the same renderers, the
    same silence rules (an invalid traceparent is dropped, an unstated cache policy renders
    nothing, an empty overlay renders an explicit empty `EXTRA_MODELS`).
    """
    env: dict[str, str] = {
        job_env.TOPIC: topic,
        job_env.EXPRESSION: url4,
        job_env.JOB_DEADLINE_S: str(deadline_s),
        job_env.STREAM_GRACE_S: str(job_env.DEFAULT_STREAM_GRACE_S),
    }
    forwarded = valid_traceparent(traceparent)
    if forwarded is not None:
        env[job_env.TRACEPARENT] = forwarded
    if profile is not None:
        env[job_env.AIGATEWAY_PROFILE] = profile
    env.update(job_env.identity_to_env(identity or {}))
    env.update(job_env.cache_policy_to_env(cache))
    env[job_env.EXTRA_MODELS] = job_env.extra_models_to_env(extra_models).get(
        job_env.EXTRA_MODELS, ""
    )
    env[job_env.IO_CONCURRENCY] = str(io_concurrency)
    return env


def encode_message(
    topic: str,
    url4: str,
    deadline_s: int,
    *,
    traceparent: str | None = None,
    profile: str | None = None,
    identity: Mapping[str, str] | None = None,
    cache: CachePolicy | None = None,
    io_concurrency: int = DEFAULT_IO_CONCURRENCY,
    extra_models: Sequence[str] = (),
) -> bytes:
    """Encode a run submission as the queue message body: the per-run env mapping, JSON."""
    return json.dumps(
        _env_mapping(
            topic,
            url4,
            deadline_s,
            traceparent=traceparent,
            profile=profile,
            identity=identity,
            cache=cache,
            io_concurrency=io_concurrency,
            extra_models=extra_models,
        ),
        sort_keys=True,
    ).encode("utf-8")


def decode_message(payload: bytes) -> dict[str, str]:
    """Decode a queue message body back into the per-run env mapping."""
    return json.loads(payload.decode("utf-8"))


def topic_of_message(payload: bytes) -> str:
    """The run's topic, read from the message body — the dedupe key.

    WHY read from the body rather than a separate argument: the codec is the single source of
    truth, so the dedupe key can never disagree with the run the message actually describes.
    """
    return decode_message(payload)[job_env.TOPIC]


STREAM_NAME_IN_USE = 10058
"""JetStream's err_code for "stream name already in use" — the ONE `BadRequestError` the
queue treats as benign. The type alone cannot say: the server answers a real configuration
conflict (retention, storage, replicas diverged — an operator edit, or a version-skewed
rolling deploy) with the SAME 400 type. Swallowing that would run the queue on settings
nobody agreed to, silently — so only this code is "already declared"; anything else raises."""


def _is_stream_name_in_use(exc: BadRequestError) -> bool:
    """Whether a `BadRequestError` from `add_stream` is the benign name-in-use case."""
    return getattr(exc, "err_code", None) == STREAM_NAME_IN_USE


class RunQueue:
    """The durable, deduplicating run queue: publish on the serving side, pull on the worker
    side, both against one JetStream stream.

    WHY a fresh connection story rather than reusing `_JetStreamConnection`: that class is
    per-topic-stream machinery (ensure/declare/sweep/delete keyed by topic) the queue must not
    inherit — the queue is ONE stream for every run. The lazy, locked, reconnectable connection
    is the only part worth sharing, and it is small enough to state here.
    """

    def __init__(
        self,
        nats_url: str,
        *,
        stream: str = subjects.RUN_QUEUE_STREAM,
        subject: str = subjects.RUN_QUEUE_SUBJECT,
        duplicate_window_s: float = DEFAULT_DUPLICATE_WINDOW_S,
        max_age_s: float = DEFAULT_QUEUE_MAX_AGE_S,
        ack_wait_s: float = DEFAULT_ACK_WAIT_S,
        max_deliver: int = DEFAULT_MAX_DELIVER,
        max_ack_pending: int = DEFAULT_MAX_ACK_PENDING,
        state_cache_ttl_s: float = DEFAULT_STATE_CACHE_TTL_S,
        # WHY a parameter at all: the replica count is a property of the BROKER's topology, not
        # of this code — a single-node broker refuses `replicas > 1` outright. Every composition
        # root feeds this from `Settings.run_queue_replicas`, which the chart renders, so a
        # clustered deployment raises it without touching Python. The default is single-node
        # safe; see `QUEUE_REPLICAS`.
        replicas: int = QUEUE_REPLICAS,
    ) -> None:
        self._url = nats_url
        self._stream = stream
        self._subject = subject
        self._duplicate_window_s = duplicate_window_s
        self._max_age_s = max_age_s
        self._ack_wait_s = ack_wait_s
        self._max_deliver = max_deliver
        self._max_ack_pending = max_ack_pending
        self._state_cache_ttl_s = state_cache_ttl_s
        self._replicas = replicas
        self._nc: Client | None = None
        self._js: JetStreamContext | None = None
        self._connect_lock = asyncio.Lock()
        self._ensured = False
        # (monotonic time of the read, (depth, first_ts)) — see `_state`.
        self._state_cache: tuple[float, tuple[int, str | None]] | None = None

    async def _jetstream(self) -> JetStreamContext:
        js = self._js
        if js is not None and not self._is_closed():
            return js
        async with self._connect_lock:
            js = self._js
            if js is not None and not self._is_closed():
                return js
            nc = await nats.connect(self._url)
            self._nc = nc
            js = nc.jetstream()
            self._js = js
            # The declarations belonged to the connection that just died; the new one has none.
            self._ensured = False
            return js

    def _is_closed(self) -> bool:
        nc = self._nc
        return nc is not None and nc.is_closed

    async def ensure_stream(self) -> None:
        """Declare the queue stream, tolerating one that already exists.

        INVARIANT: unlike the per-run event streams, the queue is a SINGLETON — one stream for
        every run — so this is a plain idempotent flag rather than the per-topic memo the event
        adapters keep.
        """
        if self._ensured:
            return
        js = await self._jetstream()
        try:
            await js.add_stream(
                name=self._stream,
                subjects=[self._subject],
                retention=RetentionPolicy.WORK_QUEUE,
                storage=StorageType.FILE,
                num_replicas=self._replicas,
                max_age=self._max_age_s,
                duplicate_window=self._duplicate_window_s,
            )
        except BadRequestError as exc:
            if not _is_stream_name_in_use(exc):
                # A config conflict wearing the same type — retention, storage, or replicas
                # diverged from what this code declares. NOT "already declared": raising here
                # surfaces the mismatch at startup instead of running on it silently.
                raise
            # Already declared — by another replica, or by an earlier connection.
            pass
        self._ensured = True

    async def publish(self, message: bytes) -> None:
        """Publish one run submission, durably.

        INVARIANT: `Nats-Msg-Id` is the run's TOPIC, read from the message body itself, so a
        retried submission of the same topic is deduplicated by the broker within
        `duplicate_window` — the queue's `JobAlreadyExists` equivalent, with no lookup table.
        The acknowledgement is awaited: the caller must know the run was durably accepted
        before it tells the client so.

        The publish also stamps `Url4-Enqueued-At` (see `subjects.ENQUEUED_AT_HEADER`): the
        wall-clock acceptance moment. JetStream's delivery metadata carries only the PULL
        timestamp, so the claim-time "waited past its deadline" check would otherwise measure
        an always-fresh ~0 and never fire for exactly the backlogged runs it exists to catch.
        """
        await self.ensure_stream()
        js = await self._jetstream()
        await js.publish(
            self._subject,
            message,
            headers={
                "Nats-Msg-Id": topic_of_message(message),
                subjects.ENQUEUED_AT_HEADER: datetime.now(UTC).isoformat(),
            },
        )

    async def pull(self, batch: int, timeout_s: float) -> list[Msg]:
        """Pull up to `batch` queued messages, waiting up to `timeout_s` for the first.

        Returns the raw NATS messages; the caller acks each after processing. Under the
        EXPLICIT ack policy an unacked message is redelivered after `ack_wait`, up to
        `max_deliver` times.

        WHY a fresh subscription per call: the durable consumer (`url4-runners`) is server-side
        and persists, so binding and unbinding a client subscription per pull is idempotent and
        costs one `consumer_info` round trip. A worker that wants to avoid even that can hold
        the subscription itself.
        """
        await self.ensure_stream()
        js = await self._jetstream()
        sub = await js.pull_subscribe(
            self._subject,
            durable=QUEUE_CONSUMER,
            stream=self._stream,
            config=_work_queue_consumer_config(
                ack_wait_s=self._ack_wait_s,
                max_deliver=self._max_deliver,
                max_ack_pending=self._max_ack_pending,
            ),
        )
        try:
            return await sub.fetch(batch, timeout=timeout_s)
        except TimeoutError:
            # INVARIANT: an idle poll is a RESULT, not an error. nats-py's `fetch` RAISES
            # `nats.errors.TimeoutError` (or its `FetchTimeoutError` subclass) when no
            # message arrives within the window — it never returns an empty list — and
            # both subclass `TimeoutError`. Left uncaught, the first empty poll unwinds
            # the worker's claim loop and kills the pool on an idle queue.
            return []
        finally:
            await sub.unsubscribe()

    async def _state(self) -> tuple[int, str | None]:
        """(queued message count, first message's publish timestamp) from one stream-info round
        trip, cached for `state_cache_ttl_s`.

        WHY the raw API request rather than `js.stream_info`: nats-py's `StreamState` drops
        `first_ts` (the server sends it; the dataclass does not model it), and `oldest_age`
        needs exactly that field. The raw response is the only path to it, so one request
        serves both signals.

        The dependency on the PRIVATE surface (`_api_request`, `_prefix`) is pinned by
        `test_nats_private_api_surface.py`: a `uv lock` bump that renames either — or a
        release that finally models `first_ts` on `StreamState` — fails that test loudly at
        CI instead of surfacing as admission logic silently misbehaving at runtime.
        """
        now = time.monotonic()
        if self._state_cache is not None and now - self._state_cache[0] < self._state_cache_ttl_s:
            return self._state_cache[1]
        js = await self._jetstream()
        resp = await js._api_request(f"{js._prefix}.STREAM.INFO.{self._stream}", b"")
        state = resp.get("state", {})
        result = (int(state.get("messages", 0)), state.get("first_ts"))
        self._state_cache = (now, result)
        return result

    async def depth(self) -> int:
        """How many runs are queued but not yet started (cached ~`state_cache_ttl_s`)."""
        messages, _ = await self._state()
        return messages

    async def oldest_age(self) -> float | None:
        """Seconds since the oldest queued run was published; `None` when the queue is empty."""
        messages, first_ts = await self._state()
        # WHY the message COUNT is the emptiness signal: the server always sends a
        # `first_ts`, answering an EMPTY stream with the Go zero time
        # ("0001-01-01T00:00:00Z"), which `fromisoformat` parses happily. A `None`-only
        # check reads that as a ~6.4e10-second age and the idle-queue alert fires
        # permanently on every drained queue.
        if not messages or first_ts is None:
            return None
        ts = datetime.fromisoformat(first_ts)
        # Belt-and-braces for a response that disagrees with itself (messages > 0 with
        # a zero time): no real run was published in year 1.
        if ts.year <= 1:
            return None
        return (datetime.now(UTC) - ts).total_seconds()

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.close()


__all__ = [
    "DEFAULT_ACK_WAIT_S",
    "DEFAULT_DEPTH_CEILING",
    "DEFAULT_DUPLICATE_WINDOW_S",
    "DEFAULT_IO_CONCURRENCY",
    "DEFAULT_MAX_ACK_PENDING",
    "DEFAULT_MAX_DELIVER",
    "DEFAULT_QUEUE_MAX_AGE_S",
    "DEFAULT_STATE_CACHE_TTL_S",
    "DEFAULT_WORKER_SLOTS",
    "QUEUE_CONSUMER",
    "QUEUE_REPLICAS",
    "RunQueue",
    "decode_message",
    "encode_message",
    "topic_of_message",
]
