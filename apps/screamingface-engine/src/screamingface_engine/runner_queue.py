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
# The margin added to the stream grace before an ABSENT stream is trusted as evidence that a run
# finished. It covers the gap between "the run ended" and "the reclamation actually landed":
# `run_and_reclaim` sleeps the grace and THEN calls `delete_stream`, and both the sleep and the
# delete run on a busy worker against a possibly-retrying broker. Half the grace again, so the
# threshold stays the same order of magnitude as the mechanism it waits for.
_RECLAIM_EVIDENCE_MARGIN_S = 30.0
# How old a reservation must be before a MISSING stream releases it (OME-1108 follow-up).
#
# WHY absence is evidence and not unknown: `runner/main.py::run_and_reclaim` deletes a run's
# stream in a `finally`, `job_env.DEFAULT_STREAM_GRACE_S` after the run ended — strictly AFTER
# the run is over — so a stream that is gone belongs to a run that finished. That is what makes
# this a release and not a weakening of "unknown never frees a slot": a broker that cannot
# ANSWER is still unknown and still releases nothing.
#
# WHY an age gate at all: absence has one other cause — a stream that does not exist YET. The
# WS attach creates it (`JetStreamConsumer.subscribe` -> `ensure_stream`) and the 428 gate makes
# that attach precede admission, but the two are separate awaits, and the worker re-ensures the
# stream at claim time. A reservation younger than this threshold is therefore treated as
# starting, not finished — otherwise a caller could exceed its cap the instant it reached it.
DEFAULT_RECLAIM_EVIDENCE_AFTER_S = job_env.DEFAULT_STREAM_GRACE_S + _RECLAIM_EVIDENCE_MARGIN_S
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
    profile: str | None = None,
    identity: Mapping[str, str] | None = None,
    cache: CachePolicy | None = None,
    io_concurrency: int = DEFAULT_IO_CONCURRENCY,
    extra_models: Sequence[str] = (),
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
        """
        await self.ensure_stream()
        js = await self._jetstream()
        await js.publish(
            self.bucket_subject(identity),
            message,
            headers={
                "Nats-Msg-Id": topic_of_message(message),
                subjects.ENQUEUED_AT_HEADER: datetime.now(UTC).isoformat(),
            },
        )

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
        messages (or the batch's fair share, whichever is larger) per bucket per visit, in
        TWO phases: a FAST pass whose short per-bucket windows collect what is immediately
        available — a burst sitting in one bucket — and a slow pass that spends the
        remaining budget on a second rotation, so a message that is not there yet still
        has a window to land. A busy caller cannot drain ahead of a quieter one WITHIN a
        pull (the per-visit cap sees to that), and the rotation index advances so no
        bucket is permanently first. A poll against an empty queue returns within
        `timeout_s` overall: the fast pass is capped at `PULL_FAST_PASS_S`, and the slow
        pass only re-splits what remains.

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
        an accident): one pull costs one `fetch` per bucket VISITED — the fast pass
        always costs a full rotation (16 with the default bucket count); the slow pass
        only runs while the batch is unfilled and budget remains — against one
        `fetch(batch)` for a single-subject consumer. That multiplier is the price of
        per-caller fairness: JetStream dispatches one consumer in stream order, so a
        single wildcard consumer would collapse the buckets back into FIFO — the exact
        head-of-line unfairness the bucket rotation exists to break. Two properties keep
        the cost bounded: the fast pass's windows total `min(PULL_FAST_PASS_S,
        timeout_s)`, and an empty bucket's fetch returns as soon as its own short window
        expires, so a poll against an empty queue is 16 cheap timeouts plus at most one
        more rotation of the REMAINING budget — never more than `timeout_s` overall.
        Revisit only with production RPC-budget numbers from the sized fleet (worker pods
        x polls/second x buckets vs what the broker absorbs); the levers, in order of
        preference, are a smaller `bucket_count`, the per-visit cap, or a server-side
        fair consumer if JetStream ever ships one — never a silent fallback to the
        wildcard.
        """
        subjects = list(subjects) if subjects is not None else self.bucket_subjects()
        if not subjects or batch <= 0:
            return []
        await self.ensure_stream()
        js = await self._jetstream()
        collected: list[Msg] = []
        # TWO PHASES over the same rotation (review follow-up P2-7). The FAST pass (the
        # first rotation) gives each bucket a short window so messages that are already
        # there — a burst sitting in one bucket — are collected before the budget is
        # spent waiting on empty buckets; the SLOW pass spends the remaining budget on a
        # second rotation, so a message that lands mid-poll still has a window. Each
        # visit fetches at most `per_visit` messages, so a busy caller cannot drain ahead
        # of a quieter one WITHIN a pull, and the total wait never exceeds `timeout_s`.
        rotation = len(subjects)
        per_visit = max(PULL_BUCKET_BATCH, -(-batch // rotation))
        fast_window = min(PULL_FAST_PASS_S, timeout_s) / rotation
        deadline = time.monotonic() + timeout_s
        for slot in range(max(batch, 2 * rotation)):
            if len(collected) >= batch:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            window = fast_window if slot < rotation else remaining / rotation
            subject = subjects[(self._rr_index + slot) % rotation]
            sub = await self._bound_subscription(js, subject)
            want = min(batch - len(collected), per_visit)
            fetched = await self._visit(sub, subject, want, window, have=len(collected))
            if fetched is None:
                break
            collected.extend(fetched)
        self._rr_index = (self._rr_index + 1) % rotation
        return collected

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

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.close()


__all__ = [
    "DEFAULT_ACK_WAIT_S",
    "DEFAULT_BUCKET_COUNT",
    "DEFAULT_CALLER_INFLIGHT_CAP",
    "DEFAULT_DEPTH_CEILING",
    "DEFAULT_DUPLICATE_WINDOW_S",
    "DEFAULT_IO_CONCURRENCY",
    "DEFAULT_MAX_ACK_PENDING",
    "DEFAULT_MAX_DELIVER",
    "DEFAULT_QUEUE_MAX_AGE_S",
    "DEFAULT_RECLAIM_EVIDENCE_AFTER_S",
    "DEFAULT_RESERVATION_LEASE_S",
    "DEFAULT_STATE_CACHE_TTL_S",
    "DEFAULT_WORKER_SLOTS",
    "PULL_BUCKET_BATCH",
    "PULL_FAST_PASS_S",
    "QUEUE_CONSUMER",
    "QUEUE_REPLICAS",
    "RunQueue",
    "caller_key",
    "decode_message",
    "encode_message",
    "topic_of_message",
]
