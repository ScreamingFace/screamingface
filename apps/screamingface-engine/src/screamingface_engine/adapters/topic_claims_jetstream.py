"""The deployed `TopicClaims`: the NATS key-value bucket `url4-claims` (E5 P2 spec D7, R3).

FEATURE: a detached Run (OME-1837). A worker claims a driver-started run's topic here before it
runs it, so of two copies of one start exactly one runs.

INVARIANT: both writes are conditional on the key's last revision, which the broker checks
atomically. A claim is a write expecting no entry (revision 0), so only one of two workers'
writes lands; a takeover and a finish expect the revision the worker read, so only one of two
contenders lands.

LAYERING: a shared leaf beside `adapters.jetstream`. The worker imports it.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from typing import Any, cast

import nats
import nats.errors
from nats.aio.client import Client
from nats.js.api import DiscardPolicy, RetentionPolicy, StorageType, StreamConfig
from nats.js.errors import APIError, KeyNotFoundError, KeyWrongLastSequenceError, NotFoundError
from nats.js.kv import KeyValue

from screamingface_engine.adapters.jetstream import (
    STREAM_NAME_IN_USE_ERR_CODE,
    EventsStreamConfig,
)
from screamingface_engine.topic_claims import (
    Claim,
    TopicClaimsUnavailable,
    decode_claim,
    encode_claim,
)

logger = logging.getLogger(__name__)

TOPIC_CLAIMS_BUCKET = "url4-claims"
# JetStream's default; it must not exceed the age, so a shorter age shortens it.
_DUPLICATE_WINDOW_S = 120.0


@dataclass(frozen=True)
class TopicClaimsBucketConfig:
    """The bucket. Defaults are the event stream's chart defaults (spec §4.4)."""

    bucket: str = TOPIC_CLAIMS_BUCKET
    max_age_s: float = 86_400.0
    replicas: int = 1
    storage: StorageType = StorageType.FILE

    @classmethod
    def for_events(cls, events: EventsStreamConfig) -> TopicClaimsBucketConfig:
        """WHY the event stream's retention: a claim then lasts as long as the topic's terminal
        frame, which a worker also reads before it runs a copy (R3)."""
        return cls(max_age_s=events.max_age_s, replicas=events.replicas, storage=events.storage)

    @property
    def stream(self) -> str:
        """The stream behind the bucket, by nats-py's naming, so `key_value` binds to it."""
        return f"KV_{self.bucket}"

    def stream_config(self) -> StreamConfig:
        # The stream nats-py's `create_key_value` would make for a bucket of history 1.
        return StreamConfig(
            name=self.stream,
            subjects=[f"$KV.{self.bucket}.>"],
            retention=RetentionPolicy.LIMITS,
            storage=self.storage,
            discard=DiscardPolicy.NEW,
            max_age=self.max_age_s,
            max_msgs_per_subject=1,
            duplicate_window=min(self.max_age_s, _DUPLICATE_WINDOW_S),
            num_replicas=self.replicas,
            allow_rollup_hdrs=True,
            deny_delete=True,
            allow_direct=True,
        )


# The fields startup applies to a live bucket; the others are fixed at creation.
_MUTABLE_FIELDS = ("max_age", "duplicate_window", "num_replicas")
_IMMUTABLE_FIELDS = ("storage", "retention")


class TopicClaimsBucketConfigError(RuntimeError):
    """The bucket exists with a storage or retention this code cannot run on. Startup fails."""


def _key(topic: str) -> str:
    """WHY a checksum: a key allows few characters, and a topic may hold any of them."""
    return hashlib.sha256(topic.encode()).hexdigest()


def _or_unavailable[F: Callable[..., Coroutine[Any, Any, Any]]](method: F) -> F:
    """Name every broker failure `TopicClaimsUnavailable`, which the worker acts on (R3)."""

    @functools.wraps(method)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await method(*args, **kwargs)
        except (nats.errors.Error, OSError) as exc:
            raise TopicClaimsUnavailable(f"the topic claims bucket: {exc!r}") from exc

    # WHY the cast: the wrapper takes and returns what the method does, so the adapter still
    # matches the `TopicClaims` Protocol.
    return cast(F, wrapper)


class JetStreamTopicClaims:
    """`TopicClaims` over one lazily opened NATS connection."""

    def __init__(self, nats_url: str, *, config: TopicClaimsBucketConfig | None = None) -> None:
        self._url = nats_url
        self.config = config if config is not None else TopicClaimsBucketConfig()
        self._nc: Client | None = None
        self._kv: KeyValue | None = None
        self._connect_lock = asyncio.Lock()

    async def _connection(self) -> Client:
        nc = self._nc
        if nc is not None and not nc.is_closed:
            return nc
        # WHY the lock: claims run concurrently, and two racing connects would leak one.
        async with self._connect_lock:
            if self._nc is None or self._nc.is_closed:
                self._nc = await nats.connect(self._url)
                self._kv = None
            return self._nc

    async def _bucket(self) -> KeyValue:
        nc = await self._connection()
        if self._kv is None:
            self._kv = await nc.jetstream().key_value(self.config.bucket)
        return self._kv

    async def ensure_bucket(self, *, update: bool = False) -> None:
        """Look, then create the bucket only if it is missing.

        WHY not nats-py's `create_key_value`: it adds the stream without looking, as
        `ensure_events_stream` (`adapters/jetstream.py`) explains the Engine never does.
        INVARIANT: without ``update`` a live bucket is never rewritten.
        """
        js = (await self._connection()).jetstream()
        wanted = self.config.stream_config()
        try:
            current = (await js.stream_info(self.config.stream)).config
        except NotFoundError:
            try:
                await js.add_stream(wanted)
                return
            except APIError as exc:
                # WHY: every worker declares it at the same startup; reconcile against the
                # one that created it first.
                if exc.err_code != STREAM_NAME_IN_USE_ERR_CODE:
                    raise
                current = (await js.stream_info(self.config.stream)).config
        for field in _IMMUTABLE_FIELDS:
            if getattr(current, field) != getattr(wanted, field):
                raise TopicClaimsBucketConfigError(
                    f"bucket {self.config.bucket!r}: `{field}` is {getattr(current, field)}, "
                    f"expected {getattr(wanted, field)}; it cannot change on a live bucket"
                )
        if update and any(getattr(current, f) != getattr(wanted, f) for f in _MUTABLE_FIELDS):
            owned = {field: getattr(wanted, field) for field in _MUTABLE_FIELDS}
            await js.update_stream(replace(current, **owned))
            logger.info("bucket %s: applied changed limits", self.config.bucket)

    @_or_unavailable
    async def claim(self, topic: str, worker_id: str) -> Claim:
        kv = await self._bucket()
        key = _key(topic)
        value = encode_claim(worker_id, finished=False)
        while True:
            try:
                return Claim(worker_id, await kv.update(key, value, last=0))
            except KeyWrongLastSequenceError:
                pass
            # A refused create does not name the holder, so read the entry.
            try:
                entry = await kv.get(key)
            except KeyNotFoundError:
                # WHY again: it expired between the two calls, so a create can now land. The
                # worker's claim budget bounds the loop.
                continue
            return decode_claim(entry.value or b"", entry.revision or 0)

    @_or_unavailable
    async def take_over(self, topic: str, worker_id: str, revision: int) -> Claim | None:
        kv = await self._bucket()
        try:
            written = await kv.update(
                _key(topic), encode_claim(worker_id, finished=False), last=revision
            )
        except KeyWrongLastSequenceError:
            return None
        return Claim(worker_id, written)

    @_or_unavailable
    async def finish(self, topic: str, worker_id: str) -> None:
        kv = await self._bucket()
        key = _key(topic)
        try:
            entry = await kv.get(key)
        except KeyNotFoundError:
            return
        claim = decode_claim(entry.value or b"", entry.revision or 0)
        if claim.holder != worker_id or claim.finished:
            return
        try:
            await kv.update(key, encode_claim(worker_id, finished=True), last=claim.revision)
        except KeyWrongLastSequenceError:
            # Taken over, or expired, since the read: the claim is no longer this worker's.
            return

    async def close(self) -> None:
        if self._nc is not None and not self._nc.is_closed:
            await self._nc.drain()
        self._nc = self._kv = None


__all__ = [
    "TOPIC_CLAIMS_BUCKET",
    "JetStreamTopicClaims",
    "TopicClaimsBucketConfig",
    "TopicClaimsBucketConfigError",
]
