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
import contextlib
import hashlib
import json
import logging
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import nats

# WHY imported explicitly rather than reached through `nats`: `nats.errors` is a SUBMODULE, so
# `import nats` does not bind it. `except nats.errors.Error` in `_fetch` resolves today only
# because `nats.aio.client` below happens to import it as a side effect. That is an accident of
# the dependency's internals, and if it ever changes the `except` clause raises AttributeError
# WHILE HANDLING A BROKER ERROR — turning the guard that keeps one pull blip local into the
# failure itself.
import nats.errors
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.aio.subscription import Subscription
from nats.js import JetStreamContext
from nats.js.api import AckPolicy, ConsumerConfig, RetentionPolicy, StorageType
from nats.js.errors import BadRequestError, ServiceUnavailableError

from screamingface_engine import job_env, subjects
from screamingface_engine.client_provenance import CLIENT_VERSION_ENV, valid_version
from url4.streaming.protocol import CachePolicy
from url4.streaming.trace import valid_traceparent

logger = logging.getLogger(__name__)

# The queue is a SINGLETON — one stream for every run, like the shared events stream
# (`url4-events`) — so its properties are constants here rather than per-topic derivations.
#
# WHY 1 and not the spec's 3 (owner decision, 2026-09-03): a single-node broker refuses
# `replicas > 1` outright with `ServerError 10074`, and single-node is what the chart's own
# bundled NATS subchart ships, what local dev runs, and what the CI conformance job runs. That
# error is not a `BadRequestError`, so `ensure_stream` does not tolerate it — it escapes into
# the worker's claim loop, which logs and retries forever while every run is refused. A default
# that cannot declare its own stream on the broker the chart bundles is the wrong default.
#
# The durability this gives up is smaller than it looks: the shared events stream is already
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
# WHY not derived from `replicas × slots`: this is a PER-CONSUMER bound, and since the bucket
# split (OME-1091) there is one durable consumer PER BUCKET SUBJECT — `_bound_subscription`
# hands this same value to each. A caller hashes to exactly one bucket (`bucket_subject`), so
# it caps ONE CALLER's unacked runs. The emergent fleet ceiling is `bucket_count × this`;
# nothing enforces a single fleet total, and what actually bounds execution is the worker's
# slot count. Deriving it from fleet sizing therefore hands every caller the whole fleet's
# width, letting one caller saturate the pool at any replica count (OME-1142) — which is why
# the chart exposes `runnerPool.maxAckPending` to pin it independently.
# INVARIANT: growing the fleet must raise how many CALLERS run at once, never how many runs a
# single caller may hold.
# AIDEV-NOTE: the value binds when the consumer is CREATED — `pull_subscribe` is idempotent on
# existence, not on config, so changing it on a running queue means deleting and recreating the
# consumers, and only while drained: a consumer holding in-flight acks redelivers those runs.
DEFAULT_MAX_ACK_PENDING = 256
DEFAULT_DEPTH_CEILING = 10_000
DEFAULT_IO_CONCURRENCY = 4
DEFAULT_STATE_CACHE_TTL_S = 2.0
# The per-caller fairness seam (OME-1091): how many bucket subjects the queue is split into.
# More buckets mean fewer caller collisions (two callers sharing a bucket share its cap and its
# round-robin slot), at the cost of more subjects the worker must poll each pull.
DEFAULT_BUCKET_COUNT = 16
# The per-bucket fetch cap per rotation visit (review follow-up P2-7): ONE message per
# bucket per visit let a single caller's burst drain at ~1 run per poll — with the default
# bucket count the rest of the rotation burned the poll's budget on empty buckets while the
# burst sat in its bucket. A cap > 1 lets a burst drain several messages per visit while
# round-robin fairness survives: a bucket takes at most this many (or its fair share of a
# larger batch) per visit, never the whole poll. Pending production numbers from the sized
# fleet; the levers are this cap and `PULL_FAST_PASS_S` below.
PULL_BUCKET_BATCH = 2
# The fast pass's total budget: one rotation with a short per-bucket window, so messages
# that are IMMEDIATELY available are collected before the poll spends its budget waiting
# on empty buckets. Bounded by `timeout_s` so a short poll never over-waits.
PULL_FAST_PASS_S = 1.0
# V-5: how long a held pull subscription is trusted before it is re-bound. The durable
# consumer can be deleted/recreated server-side (the note above says that is required to
# change `max_ack_pending`), and a stale sub can fail SILENTLY — nats-py's `_fetch_n`
# returns [] on a deleted consumer rather than raising — which no error path can catch.
# The TTL bounds the silent wedge to one refresh interval; the cost is one bind per
# bucket per interval, against the per-poll bind the cache exists to avoid.
PULL_SUB_TTL_S = 300.0
# The per-caller in-flight cap (OME-1091): how many of one caller's runs may be admitted at
# once. 8 matches the Client's fan-out (`_MAX_CANDIDATES_IN_FLIGHT`), so one ordinary
# Evaluation fits while a second concurrent one is refused until the first's runs finish.
DEFAULT_CALLER_INFLIGHT_CAP = 8
# The BACKSTOP on how long one admission may hold a slot (OME-1108). The primary release is
# observation — the runner re-reads a caller's terminal frames before refusing it — and this
# covers only what observation cannot: a broker whose tails stay unreadable. Before it existed
# the sole expiry was `capability_lifetime_s` (16.3h), so a run that finished in four minutes
# could hold its slot for most of a day; a caller was then refused by its own history while the
# queue sat empty and the pool idle. One hour is far above the longest legitimate run observed
# (~6 min) and far below that lifetime, so it never fires in normal use.
DEFAULT_RESERVATION_LEASE_S = 3600.0
# The anonymous caller's key: a run with no verified identity is its own caller, so it cannot
# hide behind another caller's footprint.
_ANONYMOUS_CALLER = "anonymous"


def caller_key(identity: Mapping[str, str] | None) -> str:
    """The caller's identity value — the verified email — or the anonymous sentinel.

    The bucket key and the per-caller in-flight counter both derive from this one value, so a
    caller is one caller everywhere. The identity mapping is canonical header name → value
    (:func:`screamingface_engine.job_env.identity_from_headers`); there is exactly one
    identity header today, so the value is the mapping's single member.
    """
    if not identity:
        return _ANONYMOUS_CALLER
    return next(iter(identity.values()), _ANONYMOUS_CALLER)


def _consumer_for(subject: str) -> str:
    """The durable consumer for one bucket subject: `url4-runners-<bucket>`.

    WHY per-bucket rather than one shared name: a durable consumer is identified by
    (stream, name) and its filter subject is part of its config — reusing one name across
    buckets would UPDATE the filter on every pull, and messages pending under the old filter
    would be re-evaluated against the new one. One consumer per bucket keeps each bucket's
    ack state stable.
    """
    return f"{QUEUE_CONSUMER}-{subject.rsplit('.', 1)[-1]}"


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
# The message body is exactly the per-run env mapping the App writes onto a run. Both sides
# render through `job_env`'s renderers, so there is no second encoding to drift;
# `test_run_queue_codec.py` pins the two mappings identical.


def _env_mapping(
    topic: str,
    url4: str,
    deadline_s: int,
    *,
    traceparent: str | None = None,
    identity: Mapping[str, str] | None = None,
    cache: CachePolicy | None = None,
    answer_seed: int | None = None,
    client_version: str | None = None,
    io_concurrency: int = DEFAULT_IO_CONCURRENCY,
    extra_models: Sequence[str] = (),
    shape: job_env.RunShape = "expression",
) -> dict[str, str]:
    """The per-run env mapping a queue message carries, keyed by env name.

    Mirrors the inprocess adapter's `_env` entry for entry: the same constants, the same
    renderers, the same silence rules (an invalid traceparent is dropped, an unstated cache
    policy renders nothing, an empty overlay renders an explicit empty `EXTRA_MODELS`).
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
    env.update(job_env.identity_to_env(identity or {}))
    env.update(job_env.cache_policy_to_env(cache))
    env.update(job_env.answer_seed_to_env(answer_seed))
    version = valid_version(client_version)
    if version is not None:
        env[CLIENT_VERSION_ENV] = version
    env[job_env.EXTRA_MODELS] = job_env.extra_models_to_env(extra_models).get(
        job_env.EXTRA_MODELS, ""
    )
    env[job_env.IO_CONCURRENCY] = str(io_concurrency)
    env[job_env.SPEC_VERSION] = job_env.CURRENT_SPEC_VERSION
    # Written only for a direct run: absent means `expression`, so a default message stays
    # byte-for-byte what an old worker reads (the drained rollout keeps old workers from ever
    # seeing a `direct` one — erd.md §10).
    if shape == "direct":
        env[job_env.RUN_SHAPE] = "direct"
        env[job_env.STREAM_GRACE_S] = str(job_env.DIRECT_STREAM_GRACE_S)
    return env


def encode_message(
    topic: str,
    url4: str,
    deadline_s: int,
    *,
    traceparent: str | None = None,
    identity: Mapping[str, str] | None = None,
    cache: CachePolicy | None = None,
    answer_seed: int | None = None,
    client_version: str | None = None,
    io_concurrency: int = DEFAULT_IO_CONCURRENCY,
    extra_models: Sequence[str] = (),
    shape: job_env.RunShape = "expression",
) -> bytes:
    """Encode a run submission as the queue message body: the per-run env mapping, JSON."""
    return json.dumps(
        _env_mapping(
            topic,
            url4,
            deadline_s,
            traceparent=traceparent,
            identity=identity,
            cache=cache,
            answer_seed=answer_seed,
            client_version=client_version,
            io_concurrency=io_concurrency,
            extra_models=extra_models,
            shape=shape,
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


UNDECODABLE_BODY_ERRORS: tuple[type[Exception], ...] = (ValueError, KeyError, TypeError)
"""What `decode_message`/`topic_of_message` raise on a body this codec cannot read.

`ValueError` covers `json.JSONDecodeError` and `UnicodeDecodeError` (both subclasses);
`KeyError` is a body that decoded but names no topic; `TypeError` a payload that is not
bytes at all.

INVARIANT: every caller that decodes a body OFF the settled path — the worker's claim loop
and its supervisor — catches exactly this tuple. A body arrives from off-process, so a
foreign publisher or a codec skew across a rolling deploy can produce one at any time; left
uncaught in either place it escapes into the worker's shared TaskGroup and cancels every
co-located supervisor, each of which SIGKILLs its live child. Named once here so the two
call sites cannot drift apart."""


class RunQueueUnavailable(RuntimeError):
    """The run could not be durably queued because the broker failed — not because it is full.

    Raised by `QueueJobRunner.schedule()` in place of a `BROKER_UNAVAILABLE_ERRORS` member that
    the admission depth read or the durable publish raised (a timeout, a closed connection, no
    servers, JetStream's own 503). The broker's error is the `__cause__`.

    WHY a typed error distinct from `JobRunnerAtCapacity`: a FULL queue and an UNREACHABLE one
    are both retryable 503s at the REST edge, but only the first has a drain estimate to derive
    `Retry-After` from. Left untyped, the broker error escaped as a naked plain-text 500 — "the
    server is broken", which clients do not retry — for a fault an identical retry usually cures.
    """


BROKER_UNAVAILABLE_ERRORS: tuple[type[Exception], ...] = (
    nats.errors.TimeoutError,
    nats.errors.ConnectionClosedError,
    nats.errors.ConnectionReconnectingError,
    nats.errors.NoServersError,
    nats.errors.NoRespondersError,
    nats.errors.StaleConnectionError,
    ServiceUnavailableError,
)
"""The broker errors that mean "not reachable right now" — the ONLY ones `RunQueueUnavailable`
stands for.

INVARIANT: "retry shortly" must be true. Everything else in `nats.errors.Error` — a payload over
the limit, a bad subject, the stream-config conflict `ensure_stream` re-raises on purpose — fails
the same way on every retry, so it stays an unhandled 500: a defect an operator must see, not a
wait a client should sit through. `StaleConnectionError` covers `UnexpectedEOF`; the timeout
covers `FlushTimeoutError`."""


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
    SHARED-events-stream machinery (ensure/declare/purge keyed by TOPIC within `url4-events`)
    the queue must not inherit — the queue is its OWN separate stream (`url4-runq`), keyed by
    caller bucket, not by topic. The lazy, locked, reconnectable connection is the only part
    worth sharing, and it is small enough to state here.
    """

    def __init__(
        self,
        nats_url: str,
        *,
        stream: str = subjects.RUN_QUEUE_STREAM,
        # The stream is declared with the wildcard `<prefix>.>` (so every bucket subject
        # lands in it); the per-caller buckets derive from `subject_prefix`.
        subject_prefix: str = subjects.RUN_QUEUE_SUBJECT_PREFIX,
        bucket_count: int = DEFAULT_BUCKET_COUNT,
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
        self._subject_prefix = subject_prefix
        self._bucket_count = bucket_count
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
        # The round-robin pull's rotation: which bucket the next pull starts at. Advancing by
        # one per pull means no bucket is permanently first (or last) in the rotation.
        self._rr_index = 0
        # HELD pull subscriptions, one per distinct subject (review follow-up): binding a
        # durable consumer costs a `consumer_info` round trip, and the claim loop pulls in
        # a tight loop whenever slots are free — binding per bucket per cycle multiplied
        # that cost by the bucket count on EVERY poll, even when the queue was empty. The
        # set of subjects is the FIXED configured bucket list (or an explicit caller's
        # list), so the cache is bounded by that, not by callers or messages.
        self._pull_subs: dict[str, Any] = {}
        self._pull_subs_bound: dict[str, float] = {}
        # The longest fetch window any pull has used: a pull request stays open on the server
        # up to this long, so `release_held` waits it out before it collects late deliveries.
        self._max_window_s = 0.0
        # The wake-up subject (OME-1091 F6): a CORE-NATS subject, not a bucket subject, and
        # DELIBERATELY named outside the queue stream's wildcard filter (`<prefix>.>`, see
        # `_stream_subject`) — `<prefix>-wake` fails that match at the first character past
        # the prefix (`-` where the filter needs a `.`). If it matched, JetStream would
        # durably STORE every wake-up as a queue message, and the worker's pull would try to
        # claim it as a run. `publish` and `release_held` send a fire-and-forget nudge here;
        # `pull` subscribes to it (lazily, once per connection — `_ensure_wake_subscription`,
        # bound BEFORE every pull's fast pass) so an idle pull is nudged the moment work
        # lands, instead of waiting out a blind rotation. See
        # `test_the_wake_subject_is_outside_the_stream_subject_filter`.
        self._wake_subject = f"{subject_prefix}-wake"
        # The HELD wake subscription (one per connection, like `_pull_subs`): `None` until
        # `_ensure_wake_subscription` binds it, and reset to `None` on reconnect below —
        # the subscription died with the old connection.
        self._wake_sub: Subscription | None = None
        # Set by the wake subscription's callback; `pull`'s wait loop blocks on it once
        # its fast pass leaves the batch unfilled. Cleared at the start of every `pull`,
        # and again each time the wait loop wakes (`_wait_for_wake`).
        self._woken = asyncio.Event()
        # The TARGETED wake state (OME-1091 F6, design review's accepted fix): WHICH
        # bucket(s) a wake was actually for, so the wait loop's repeat pass visits only
        # those instead of a full rotation. `_on_wake` adds one subject per `publish`'s
        # nudge, or sets `_woken_all` for a `release_held` drain (whose given-back
        # messages can span any bucket). `_wait_for_wake` reads and clears both
        # atomically (no `await` between) right before it runs a pass, so a wake landing
        # WHILE that pass runs accumulates for the NEXT one instead of racing it.
        self._woken_subjects: set[str] = set()
        self._woken_all = False

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
            # Held subscriptions died with it too — rebind on the next pull.
            self._pull_subs.clear()
            self._pull_subs_bound.clear()
            self._wake_sub = None
            return js

    def _is_closed(self) -> bool:
        nc = self._nc
        return nc is not None and nc.is_closed

    @property
    def _stream_subject(self) -> str:
        """The stream's subject set: the wildcard over every bucket subject, so one stream
        holds every caller's runs."""
        return f"{self._subject_prefix}.>"

    def bucket_subject(self, identity: Mapping[str, str] | None) -> str:
        """The per-caller queue subject for one caller: a stable hash of the identity VALUE,
        not the raw address — a subject name is readable by anything with broker access, so
        the caller's email must never appear in it (spec open question 1).
        """
        digest = hashlib.sha256(caller_key(identity).encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % self._bucket_count
        return f"{self._subject_prefix}.{bucket:02x}"

    def bucket_subjects(self) -> list[str]:
        """Every bucket subject, in order — the round-robin pull's rotation."""
        return [f"{self._subject_prefix}.{i:02x}" for i in range(self._bucket_count)]

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
                subjects=[self._stream_subject],
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
            # Already declared — by another replica, or by an earlier connection. A stream
            # declared before per-caller buckets (OME-1091) holds only the single work subject;
            # widen it to the wildcard so bucket publishes land, without touching the rest of
            # its config (replicas, retention — those are the declaring replica's business).
            info = await js.stream_info(self._stream)
            if info.config.subjects != [self._stream_subject]:
                # INVARIANT: the update starts from the LIVE config, not from kwargs.
                # nats-py's `update_stream` builds a FRESH `StreamConfig()` and evolves
                # only the given kwargs, so `update_stream(name=..., subjects=...)`
                # resets everything not named — retention (WorkQueue -> Limits),
                # `num_replicas`, `max_age`, `duplicate_window` — to defaults. Against a
                # legacy narrow-subject stream the server then REJECTS the retention
                # change and `ensure_stream` raises on every publish; if it were
                # accepted, the dedupe window and replica count would be silently gone.
                config = info.config
                config.subjects = [self._stream_subject]
                await js.update_stream(config)
        self._ensured = True

    async def publish(self, message: bytes, *, identity: Mapping[str, str] | None = None) -> None:
        """Publish one run submission to its caller's bucket, durably.

        INVARIANT: `Nats-Msg-Id` is the run's TOPIC, read from the message body itself, so a
        retried submission of the same topic is deduplicated by the broker within
        `duplicate_window` — the queue's `JobAlreadyExists` equivalent, with no lookup table.
        The acknowledgement is awaited: the caller must know the run was durably accepted
        before it tells the client so.

        The publish also stamps `Url4-Enqueued-At` (see `subjects.ENQUEUED_AT_HEADER`): the
        wall-clock acceptance moment. JetStream's delivery metadata carries only the PULL
        timestamp, so the claim-time "waited past its deadline" check would otherwise measure
        an always-fresh ~0 and never fire for exactly the backlogged runs it exists to catch.

        WAKE-UP (OME-1091 F6): once the message is durably queued, a fire-and-forget
        core-NATS nudge on `self._wake_subject` lets an idle `pull` claim it at once instead
        of waiting out its next rotation — see `_wake`. It never fails this call: the run is
        already accepted by the time it is sent, so a missed nudge only costs the OLD
        latency, never the run.
        """
        await self.ensure_stream()
        js = await self._jetstream()
        bucket_subject = self.bucket_subject(identity)
        await js.publish(
            bucket_subject,
            message,
            headers={
                "Nats-Msg-Id": topic_of_message(message),
                subjects.ENQUEUED_AT_HEADER: datetime.now(UTC).isoformat(),
            },
        )
        await self._wake(bucket_subject.encode())

    async def pull(
        self,
        batch: int,
        timeout_s: float,
        *,
        subjects: Sequence[str] | None = None,
    ) -> list[Msg]:
        """Pull up to `batch` queued messages, round-robin across `subjects` (default: every
        bucket), waiting up to `timeout_s` in total.

        The round-robin visits every bucket in rotation, up to `PULL_BUCKET_BATCH`
        messages (or the batch's fair share, whichever is larger) per bucket per visit. A
        busy caller cannot drain ahead of a quieter one WITHIN a pull (the per-visit cap
        sees to that), and the rotation index advances so no bucket is permanently first.

        WAKE-UP (OME-1091 F6): a FAST pass — one rotation with short per-bucket windows —
        collects whatever a burst already left sitting in a bucket. What happens next
        depends on whether a wake SUBSCRIPTION exists (`_ensure_wake_subscription`, bound
        BEFORE the fast pass runs, on EVERY pull — including the first of a connection —
        so a wake landing during THIS pull's own fast pass is never lost):

        - No subscription could be made (no live connection yet, or the broker refuses
          the subscribe): `pull` falls back to the ORIGINAL behavior, BYTE FOR BYTE,
          unchanged by any of this — a slow pass spends the remaining budget on a second
          rotation, so a message that is not there yet still has a window to land, and
          the call holds for a full batch or the deadline exactly as it always has.
        - A subscription exists and the fast pass collected NOTHING: `pull` waits on
          `self._wake_subject` instead of blind-rotating again — the core-NATS nudge
          `publish` (or a drained `release_held`) sends the moment work lands. That wait
          repeats a TARGETED pass on each wake: ONLY the bucket(s) `_on_wake` recorded
          since the last one, or every bucket when a drain-wide nudge marked "all". A
          false alarm (another pod claimed first, or the nudge named buckets outside
          this pull's own list) keeps waiting rather than returning empty-handed; only
          the deadline forces an empty return.
        - A subscription exists and a pass (the fast pass, or a wake pass) collected
          SOMETHING but not the full batch: `pull` runs ONE top-up rotation over only the
          subject(s) that pass just found something in (`_top_up`), then returns — this
          is what keeps the wake path's OWN version of the OME-1091 property "one
          caller's burst fills a worker's batch" (test_one_callers_burst_fills_the_batch
          _from_one_bucket, on the fallback path) without ever holding delivered messages
          until the deadline the way blind-rotating for more would.

        Every fetch window in every pass — fast, wake, top-up, or the fallback's slow
        pass — is capped by what remains until `timeout_s`'s deadline, so none of them
        can overrun it.

        A BROKER BLIP never loses what was already collected: a pass that ends early on
        one (`_visit`'s `None`, raised only once something is already in hand) makes
        `pull` return that partial batch AT ONCE, rather than starting another pass that
        would re-bind the dropped subscription — which can raise mid-outage, and would
        otherwise unwind this call and discard delivered messages that were never acked
        or NAK'd.

        Returns the raw NATS messages; the caller acks each after processing. Under the
        EXPLICIT ack policy an unacked message is redelivered after `ack_wait`, up to
        `max_deliver` times.

        WHY subscriptions are HELD: the durable consumers (`url4-runners-<bucket>`) are
        server-side and persist, so binding a client subscription is idempotent — and
        doing it per bucket PER CYCLE cost a `consumer_info` round trip each way on every
        poll, multiplied by the bucket count, paid even when the queue was empty and the
        claim loop is polling flat out. Holding one subscription per distinct subject
        reduces each cycle to the `fetch` alone; the cache is bounded by the configured
        bucket list (or the caller's explicit list), never by callers or messages, and a
        reconnect clears it — the subscriptions died with the connection.

        THE RPC ACCOUNTING (review follow-up, recorded so the tradeoff is a decision, not
        an accident; updated for the wake-up): one pull costs one `fetch` per bucket
        VISITED — the fast pass always costs a full rotation (16 with the default bucket
        count) — against one `fetch(batch)` for a single-subject consumer. That
        multiplier is the price of per-caller fairness: JetStream dispatches one consumer
        in stream order, so a single wildcard consumer would collapse the buckets back
        into FIFO — the exact head-of-line unfairness the bucket rotation exists to
        break. An IDLE poll on the wake path now costs one fast rotation plus ONE FETCH
        per bucket a wake-up actually names — never a whole second blind rotation — and
        a partial burst costs the fast pass plus one top-up fetch per productive bucket,
        never a full second rotation either. FAN-OUT: every idle pod receives every wake, so
        one publish costs one fetch of the woken bucket PER IDLE POD (all but one lose it and
        wait out one fast window), and the winner's claim loop pulls again at once (one
        more fast rotation) — about `pods + rotation` fetches per publish, against a blind
        slow rotation per pod per `timeout_s` before. At a high publish rate across many
        idle pods that can cost MORE RPCs than the old poll; it buys milliseconds of claim
        latency. A missed wake (the notify raced the pull, or
        never arrived) simply falls back to the NEXT pull's own fast rotation rather than
        hanging. Only the fallback path (no wake subscription) still costs a second full
        rotation, exactly as before the wake-up existed. Never more than `timeout_s`
        overall either way (the fast pass's windows total `min(PULL_FAST_PASS_S,
        timeout_s)`, and every later window is capped by what remains of it). Revisit
        only with production RPC-budget numbers from the sized fleet (worker pods x
        polls/second x buckets vs what the broker absorbs); the levers, in order of
        preference, are a smaller `bucket_count`, the per-visit cap, or a server-side
        fair consumer if JetStream ever ships one — never a silent fallback to the
        wildcard.
        """
        subjects = list(subjects) if subjects is not None else self.bucket_subjects()
        if not subjects or batch <= 0:
            return []
        await self.ensure_stream()
        js = await self._jetstream()
        # Bound BEFORE the fast pass, on EVERY pull — a wake that lands
        # during THIS pull's own fast pass must still be seen, not just a later one's.
        wake_sub = await self._ensure_wake_subscription()
        self._woken.clear()
        self._woken_all = False
        self._woken_subjects.clear()
        collected: list[Msg] = []
        hits: set[str] = set()
        rotation = len(subjects)
        per_visit = max(PULL_BUCKET_BATCH, -(-batch // rotation))
        fast_window = min(PULL_FAST_PASS_S, timeout_s) / rotation
        deadline = time.monotonic() + timeout_s
        start = self._rr_index
        stopped = await self._rotate(
            js,
            subjects,
            start=start,
            visits=rotation,
            batch=batch,
            per_visit=per_visit,
            window=fast_window,
            shrink=False,
            deadline=deadline,
            collected=collected,
            productive=hits,
        )
        self._rr_index = (start + 1) % rotation
        if not stopped and len(collected) < batch and deadline - time.monotonic() > 0:
            await self._second_pass(
                js,
                subjects,
                wake_sub,
                hits,
                start,
                batch,
                per_visit,
                fast_window,
                deadline,
                collected,
            )
        return collected

    async def _second_pass(
        self,
        js: Any,
        subjects: list[str],
        wake_sub: Subscription | None,
        hits: set[str],
        start: int,
        batch: int,
        per_visit: int,
        fast_window: float,
        deadline: float,
        collected: list[Msg],
    ) -> None:
        """The pull's SECOND pass — reached only when the first fast pass hit no blip and
        left the batch unfilled, with time still remaining. Three ways this goes:

        - No wake subscription (`wake_sub` is `None`): the ORIGINAL slow pass, BYTE FOR
          BYTE unchanged by the wake-up — one more rotation spending the REMAINING
          budget, split evenly across every bucket (`shrink=True`), starting at the SAME
          rotation offset as the fast pass (`start`) — whether or not that fast pass
          already collected something (the fallback holds for a full batch or the deadline
          exactly as it always has; only the wake path below returns early on a partial
          batch).
        - A wake subscription exists and the fast pass already collected something
          (`hits` names the bucket(s) it came from): ONE top-up rotation over just those
          buckets (`_top_up`), then return — never a full wake wait, and never held for
          the deadline.
        - A wake subscription exists and the fast pass collected NOTHING: wait for a
          wake-up (`_wait_for_wake`), which applies this same top-up-then-return rule to
          each wake pass in turn.
        """
        if wake_sub is None:
            rotation = len(subjects)
            extra_slots = max(batch, 2 * rotation) - rotation
            if extra_slots > 0:
                await self._rotate(
                    js,
                    subjects,
                    start=start,
                    visits=extra_slots,
                    batch=batch,
                    per_visit=per_visit,
                    window=0.0,
                    shrink=True,
                    deadline=deadline,
                    collected=collected,
                )
            return
        if collected:
            await self._top_up(
                js, subjects, hits, batch, per_visit, fast_window, deadline, collected
            )
            return
        await self._wait_for_wake(js, subjects, batch, per_visit, fast_window, deadline, collected)

    async def _top_up(
        self,
        js: Any,
        subjects: list[str],
        hits: set[str],
        batch: int,
        per_visit: int,
        window: float,
        deadline: float,
        collected: list[Msg],
    ) -> None:
        """ONE extra rotation over only the
        bucket(s) that the pass just before this one found something in — `hits`, in
        `subjects`' own rotation order — then return, whatever it finds. This is what
        keeps the wake path's version of the OME-1091 burst property (one caller's 8
        messages in one bucket still fill a `batch=4` pull) without ever holding what is
        ALREADY collected and delivered until the deadline: a caller with a partial batch
        in hand gets it back at once, and can always poll again for the rest.

        A blip during this rotation is handled exactly like any other (`_rotate`'s own
        `stopped` return) — the caller just returns `collected` right after either way,
        so there is nothing further for this method itself to decide.
        """
        targets = [s for s in subjects if s in hits]
        if not targets:
            return
        await self._rotate(
            js,
            targets,
            start=self._rr_index,
            visits=len(targets),
            batch=batch,
            per_visit=per_visit,
            window=window,
            shrink=False,
            deadline=deadline,
            collected=collected,
        )

    async def _rotate(
        self,
        js: Any,
        subjects: list[str],
        *,
        start: int,
        visits: int,
        batch: int,
        per_visit: int,
        window: float,
        shrink: bool,
        deadline: float,
        collected: list[Msg],
        productive: set[str] | None = None,
    ) -> bool:
        """One rotation: `visits` bucket visits over `subjects`, starting at rotation
        offset `start` (mod `len(subjects)`). `visits == len(subjects)` sweeps the whole
        list once — the fast pass, and a wake or top-up pass's targeted list; a larger
        `visits` cycles it more than once — the fallback slow pass's larger batch.
        Appends to `collected` IN PLACE, and — when `productive` is given — adds every
        subject that yielded at least one message to it, so a caller (`_top_up`) can
        revisit just those. Shared by every pass so they are identical in every fairness
        property: same per-visit cap, same rotation order.

        WHY one window formula, selected by `shrink`: the fast pass, the wake pass, and
        the top-up pass all use a FIXED short `window` per visit, so a burst already
        sitting in a bucket is caught immediately; the fallback slow pass instead SPENDS
        the remaining budget, splitting it across the full rotation afresh every visit
        (`shrink=True` ignores `window` and uses `remaining / len(subjects)` instead) —
        the shrinking rule it has always used. EITHER WAY every visit's window is capped
        by what remains until `deadline`: a wake — or a slow-pass slot — landing
        near `timeout_s`'s deadline must never spend a longer window than what is
        actually left.

        Returns `True` ("stopped") the moment a visit ends on a blip (`_visit`'s `None`
        — a broker error raised only once `have` messages were already collected): the
        caller must return `collected` AT ONCE rather than starting another pass, because
        the very next visit would re-bind the dropped subscription
        (`_bound_subscription` -> `js.pull_subscribe`), which can raise mid-outage and
        would otherwise discard exactly the delivered messages this call is protecting.
        Returns `False` when the rotation ends normally: the batch filled, the visits
        ran out, or the deadline passed.
        """
        rotation = len(subjects)
        for slot in range(visits):
            if len(collected) >= batch:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            visit_window = remaining / rotation if shrink else min(window, remaining)
            self._max_window_s = max(self._max_window_s, visit_window)
            subject = subjects[(start + slot) % rotation]
            sub = await self._bound_subscription(js, subject)
            want = min(batch - len(collected), per_visit)
            fetched = await self._visit(sub, subject, want, visit_window, have=len(collected))
            if fetched is None:
                return True
            # Productive only when the visit came back FULL: a bucket that returned fewer than
            # asked ran dry inside its window, and a top-up visit would only wait it out again.
            if productive is not None and len(fetched) == want:
                productive.add(subject)
            collected.extend(fetched)
        return False

    async def _wait_for_wake(
        self,
        js: Any,
        subjects: list[str],
        batch: int,
        per_visit: int,
        fast_window: float,
        deadline: float,
        collected: list[Msg],
    ) -> None:
        """Wait for a wake-up (OME-1091 F6, targeted pass — the design review's accepted
        fix), repeating a pass on each one: ONLY the woken subjects (`_on_wake`'s
        per-`publish` nudge), or a full sweep of `subjects` when a `release_held` drain
        woke every puller ("all" — its given-back messages can span any bucket).

        Takes and clears the woken state atomically (no `await` between the read and the
        reset) BEFORE running a pass, so a wake landing WHILE that pass runs accumulates
        for the NEXT iteration instead of racing it. A wake whose subjects miss this
        pull's own list entirely — another caller's publish, restricted out by the
        intersection with `subjects` — is a false alarm: it keeps waiting rather than
        spending a pass on nothing, since only the deadline may end this loop
        empty-handed.

        A pass that STOPS on a blip returns at once, same as everywhere else. A pass
        that collects something but not the full batch runs ONE top-up rotation
        (`_top_up`) over just the bucket(s) it came from, then returns — the
        SAME rule `pull`'s own first fast pass follows — rather than waiting for a
        further wake that may never target this pull's own buckets again. Only a pass
        that collects NOTHING loops back to wait for the next wake.
        """
        subject_set = set(subjects)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                await asyncio.wait_for(self._woken.wait(), remaining)
            except TimeoutError:
                return
            self._woken.clear()
            woken_all, self._woken_all = self._woken_all, False
            targets_hit = self._woken_subjects & subject_set
            self._woken_subjects.clear()
            if not woken_all and not targets_hit:
                continue
            targets = subjects if woken_all else [s for s in subjects if s in targets_hit]
            hits: set[str] = set()
            stopped = await self._rotate(
                js,
                targets,
                start=self._rr_index,
                visits=len(targets),
                batch=batch,
                per_visit=per_visit,
                window=fast_window,
                shrink=False,
                deadline=deadline,
                collected=collected,
                productive=hits,
            )
            if stopped:
                return
            if collected:
                break
        await self._top_up(js, targets, hits, batch, per_visit, fast_window, deadline, collected)

    async def _ensure_wake_subscription(self) -> Subscription | None:
        """The lazy, HELD-per-connection subscription to `self._wake_subject`
        (OME-1091 F6): its callback (`_on_wake`) records what the wake was for and sets
        `self._woken`, which `pull`'s wait loop blocks on.

        Bound BEFORE the fast pass runs, on EVERY pull (`pull` awaits this right after
        `_jetstream`, before it resets `_woken`/`_woken_all`/`_woken_subjects`) —
        including the very first pull of a connection: a subscription bound only
        AFTER the fast pass would miss exactly the wake a concurrent publish sends while
        that fast pass is still running. Once bound it stays live for every later pull on
        this connection too.

        Returns `None`, never raising, when no subscription exists and none can be made —
        no live connection yet (`self._nc` is `None`), or the broker refuses the
        subscribe (`nats.errors.Error`) — so the caller falls back to the original slow
        pass. Reset to `None` on reconnect (`_jetstream`), like `_pull_subs`.
        """
        if self._wake_sub is None and self._nc is not None:
            try:
                self._wake_sub = await self._nc.subscribe(self._wake_subject, cb=self._on_wake)
            except nats.errors.Error:
                logger.debug(
                    "run-queue wake subscription failed; falling back to the slow pass",
                    exc_info=True,
                )
        return self._wake_sub

    async def _on_wake(self, msg: Msg) -> None:
        """The wake subscription's callback (OME-1091 F6, targeted pass — the design
        review's accepted fix): a non-empty payload is one bucket subject (`publish`'s
        nudge), recorded so the next pass visits ONLY that bucket; an empty payload
        (`release_held`'s drain-wide nudge, whose given-back messages can span any
        bucket) marks "all" instead. Either way sets `self._woken`, which `pull`'s wait
        loop blocks on.
        """
        if msg.data:
            self._woken_subjects.add(msg.data.decode())
        else:
            self._woken_all = True
        self._woken.set()

    async def _wake(self, payload: bytes) -> None:
        """Fire off a core-NATS wake-up on `self._wake_subject`, best-effort.

        Called only AFTER the run it announces is already durably queued (`publish`) or
        already NAK'd back to the queue (`release_held`), so a failure here costs only a
        missed nudge — the slow path (the fallback rotation, or the next pull's own fast
        pass) still finds the work. Never raises: a broker hiccup on the wake must not
        fail the call it follows.
        """
        nc = self._nc
        if nc is None:
            return
        try:
            await nc.publish(self._wake_subject, payload)
        except nats.errors.Error:
            logger.debug(
                "run-queue wake-up publish failed; the run is durably queued", exc_info=True
            )

    async def _visit(
        self, sub: Any, subject: str, want: int, window: float, *, have: int
    ) -> list[Any] | None:
        """One bucket visit's messages, or ``None`` when a blip should end the rotation.

        INVARIANT: a delivery attempt is never spent for nothing. `_fetch_from` re-raises a
        non-timeout broker error, and `pull` accumulates across buckets — so letting that
        escape discarded every message the earlier buckets had already yielded, along with
        the stack frame holding them. Those messages had been DELIVERED: neither acked nor
        NAK'd, they sat out the whole `ack_wait` and came back as their FINAL delivery
        (`DEFAULT_MAX_DELIVER` is 2), where one further blip ends those runs as
        `max_deliveries` instead of executing them.

        WHY a visit that follows NOTHING still raises (`have == 0`): the claim loop counts
        pull failures and backs off on them, so swallowing unconditionally would turn a
        broker outage into a silent hot loop indistinguishable from an idle queue. With
        work in hand the blip is simply left to the next pull, against the same broker.
        """
        try:
            return await self._fetch_from(sub, subject, want, window)
        except nats.errors.Error:
            if not have:
                raise
            logger.warning(
                "run-queue pull stopped early on %s after collecting %d message(s); "
                "returning them and leaving the blip to the next pull",
                subject,
                have,
                exc_info=True,
            )
            return None

    async def _fetch_from(self, sub: Any, subject: str, want: int, window: float) -> list[Any]:
        """One bucket visit: fetch up to `want` messages, clamped to `want`.

        INVARIANT: an empty bucket is a RESULT, not an error. nats-py's `fetch` RAISES
        `nats.errors.TimeoutError` (or its `FetchTimeoutError` subclass) when no message
        arrives within the window — it never returns an empty list — and both subclass
        `TimeoutError`. Left uncaught, the first empty bucket in the rotation unwinds the
        worker's claim loop and kills the pool; with 16 buckets most rotations visit
        empty buckets before the one that holds a message. A timed-out HELD subscription
        stays usable — the next fetch on it is an independent request.

        V-4: nats-py's `_fetch_n` (want >= 2) drains the subscription's PENDING queue
        with no `needed` guard, so a held sub carrying late deliveries from a previous
        poll can return MORE than `want` — and the claim loop spawns one supervisor per
        returned message, so an unclamped extend over-subscribed the pod past
        `worker_slots`, breaking the loop's stated invariant. The surplus is NAK'd —
        returned to the queue for the next pull — not dropped and not acked away.

        V-5: a held subscription can be broken server-side — the durable consumer deleted
        or recreated (the note above says that is required to change `max_ack_pending`)
        — and a broken sub never self-heals: `_fetch_one` raises, `_fetch_n` returns []
        silently. A non-timeout error drops the cache entry so the next pull re-binds;
        the claim loop's guard logs and retries, and the wedge is bounded to one poll.
        """
        try:
            msgs = await sub.fetch(want, timeout=window)
        except TimeoutError:
            return []
        except nats.errors.Error:
            self._pull_subs.pop(subject, None)
            self._pull_subs_bound.pop(subject, None)
            raise
        if len(msgs) > want:
            surplus, msgs = msgs[want:], msgs[:want]
            for extra in surplus:
                await extra.nak()
        return msgs

    async def _bound_subscription(self, js: Any, subject: str) -> Any:
        """The HELD pull subscription for one bucket subject, bound on first use.

        WHY held and not per-cycle: binding a durable consumer costs a `consumer_info`
        round trip, and the claim loop pulls in a tight loop — per-cycle binding paid
        that once per bucket PER POLL, even against an empty queue. The cache is bounded
        by the configured bucket list and cleared on reconnect (the subscriptions died
        with the connection)."""
        sub = self._pull_subs.get(subject)
        if (
            sub is not None
            and time.monotonic() - self._pull_subs_bound.get(subject, 0.0) > PULL_SUB_TTL_S
        ):
            # V-5: the TTL refresh — a stale sub can fail silently (see the constant), so
            # it is re-bound on a schedule rather than only on a visible error.
            self._pull_subs.pop(subject, None)
            sub = None
        if sub is None:
            sub = await js.pull_subscribe(
                subject,
                durable=_consumer_for(subject),
                stream=self._stream,
                config=_work_queue_consumer_config(
                    ack_wait_s=self._ack_wait_s,
                    max_deliver=self._max_deliver,
                    max_ack_pending=self._max_ack_pending,
                ),
            )
            self._pull_subs[subject] = sub
            self._pull_subs_bound[subject] = time.monotonic()
        return sub

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

    async def release_held(self) -> int:
        """Give back every message a held subscription buffered that no pull returned.

        WHY (kind K8 finding): a fetch that times out on the client leaves its pull request
        open on the server for the rest of its window, and a message that arrives then lands
        in the held subscription's buffer — a DELIVERY no pull has returned. While the claim
        loop runs, the next pull picks it up (V-4). A draining worker pulls no more, so that
        message sat unacked for the whole `ack_wait` (60 s) before any other pod could take
        it: a mount call on the next pod waited past its 30 s bound and answered 504.

        Call it once the claim loop has stopped. It waits out the last window (the server
        closes the open pull requests), NAKs every buffered message so it is redelivered at
        once, and unsubscribes — the queue's OWN pull subscriptions AND its wake
        subscription (OME-1091 F6): a draining pod stops pulling, so it has no more use
        for the wake-up either, and a stale callback on a closing connection is one less
        thing to reason about. Status messages (a pull's 408/404 end) carry no delivery
        and are skipped. Returns the number of messages given back.
        """
        if not self._pull_subs:
            await self._disarm_wake_subscription()
            return 0
        await asyncio.sleep(self._max_window_s)
        released = 0
        subs = list(self._pull_subs.values())
        self._pull_subs.clear()
        self._pull_subs_bound.clear()
        for sub in subs:
            # AIDEV-NOTE: nats-py exposes the buffer only as `pending_msgs` (a count); the
            # queue behind it is `_sub._pending_queue`. `get_nowait` never blocks.
            buffered = sub._sub._pending_queue  # noqa: SLF001
            while not buffered.empty():
                msg = buffered.get_nowait()
                if msg.reply and not JetStreamContext.is_status_msg(msg):
                    with contextlib.suppress(nats.errors.Error):
                        await msg.nak()
                        released += 1
            with contextlib.suppress(nats.errors.Error):
                await sub.unsubscribe()
        await self._disarm_wake_subscription()
        if released:
            # The NAKs above must actually reach the broker before the wake-up below —
            # otherwise another pod's idle pull could wake, pass, and find nothing yet.
            # Bounded and best-effort, like every other step here: a flush that times out
            # still leaves the NAKs in flight, and the wake below costs only a missed
            # nudge, never the given-back runs (V-4 still picks them up next pull).
            nc = self._nc
            if nc is not None:
                with contextlib.suppress(nats.errors.Error, TimeoutError):
                    await nc.flush(timeout=1)  # inside the drain grace: bounded
            logger.info("run-queue drain gave back %d buffered message(s)", released)
            # OME-1091 F6: another pod's idle pull may be sitting in its wake wait right
            # now — nudge it so it claims the given-back runs at once instead of waiting
            # out its own rotation. No bucket in the payload: the given-back messages can
            # span any of them, so every waiting puller does a full pass, not a targeted
            # one (`_on_wake`'s "all").
            await self._wake(b"")
        return released

    async def _disarm_wake_subscription(self) -> None:
        """Unsubscribe the wake subscription and forget it (OME-1091 F6, `release_held`
        item): a draining pod stops pulling, so it has no more use for the wake-up, and
        best-effort like every other step here — a broker hiccup on the unsubscribe must
        not stop the drain it follows."""
        wake_sub, self._wake_sub = self._wake_sub, None
        if wake_sub is not None:
            with contextlib.suppress(nats.errors.Error):
                await wake_sub.unsubscribe()

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.close()


__all__ = [
    "BROKER_UNAVAILABLE_ERRORS",
    "DEFAULT_ACK_WAIT_S",
    "DEFAULT_BUCKET_COUNT",
    "DEFAULT_CALLER_INFLIGHT_CAP",
    "DEFAULT_DEPTH_CEILING",
    "DEFAULT_DUPLICATE_WINDOW_S",
    "DEFAULT_IO_CONCURRENCY",
    "DEFAULT_MAX_ACK_PENDING",
    "DEFAULT_MAX_DELIVER",
    "DEFAULT_QUEUE_MAX_AGE_S",
    "DEFAULT_RESERVATION_LEASE_S",
    "DEFAULT_STATE_CACHE_TTL_S",
    "DEFAULT_WORKER_SLOTS",
    "PULL_BUCKET_BATCH",
    "PULL_FAST_PASS_S",
    "QUEUE_CONSUMER",
    "QUEUE_REPLICAS",
    "RunQueue",
    "RunQueueUnavailable",
    "caller_key",
    "decode_message",
    "encode_message",
    "topic_of_message",
]
