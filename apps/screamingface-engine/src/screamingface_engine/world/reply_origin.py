"""Where one model reply came from: a live call, the gateway cache, or a frozen-copy replay.

FEATURE: a recorded judge reply is final (spec ``2026-10-16-judge-redraw-live-only``). A judge
step may redraw an unusable reply only when that reply was LIVE; a reply the gateway served from
its cache, or one replayed from a frozen copy, is the recording, and asking again would replace
the recorded verdict with a fresh, paid one.

The connector is the one place that knows the origin (it reads the gateway's cache outcome and
knows when it replays a copy), and the judge step is the one place that needs it. Between them
sit the node's dispatch and url4, which carry text only. So the caller opens a WATCH around its
call, and the connector records each round trip's origin into it:

    with watch_reply_origin() as watch:
        completion = await fetch(target)   # the connector calls record_reply_origin(...)
    watch.origin                           # "live" | "cache" | "replay" | None

INVARIANT: the watch is a shared mutable object held in a ContextVar. A child task inherits a COPY
of the context, and the copy points at the same object, so a call dispatched in its own task
still reaches its caller's watch. Setting a ContextVar inside the callee would not.

INVARIANT: recording with no watch open is a no-op. Almost every model call (every Candidate
answer) has no watcher, and an observation must never fail a call.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal

from screamingface_engine.world.cache_readback import CacheOutcome

ReplyOrigin = Literal["live", "cache", "replay"]
"""``live``: the provider answered this call. ``cache``: the gateway served a stored reply.
``replay``: a frozen copy answered (OME-1307)."""

#: The origins whose reply is a recording, never to be redrawn (spec R2).
RECORDED_ORIGINS: frozenset[ReplyOrigin] = frozenset({"cache", "replay"})


@dataclass(slots=True)
class ReplyOriginWatch:
    """What one watched call learned: the origin of its LAST round trip, or ``None`` when no
    round trip answered (the call failed, or never reached the connector)."""

    origin: ReplyOrigin | None = None


_watch: ContextVar[ReplyOriginWatch | None] = ContextVar(
    "screamingface_reply_origin_watch", default=None
)


@contextmanager
def watch_reply_origin() -> Iterator[ReplyOriginWatch]:
    """Open a watch for the calls made inside this block; the outer watch returns after it."""

    watch = ReplyOriginWatch()
    token: Token[ReplyOriginWatch | None] = _watch.set(watch)
    try:
        yield watch
    finally:
        _watch.reset(token)


def record_reply_origin(origin: ReplyOrigin) -> None:
    """Record one answered round trip's origin into the open watch, if any.

    WHY the last one wins: a call with a tool loop makes several round trips, and the reply the
    caller acts on is the last one's.
    """

    watch: ReplyOriginWatch | None = _watch.get()
    if watch is not None:
        watch.origin = origin


def round_trip_origin(cache: CacheOutcome | None, replay_frozen_copy: str | None) -> ReplyOrigin:
    """The origin of one answered round trip, from the facts the connector holds.

    A replay is a replay whatever the copy's stored headers say. A ``hit`` is the gateway cache.
    Anything else is live, including no reported outcome at all (spec R4: an unknown origin
    keeps today's behaviour; a wrongly "recorded" reply would silently stop a needed redraw).
    """

    if replay_frozen_copy is not None:
        return "replay"
    if cache is not None and cache.status == "hit":
        return "cache"
    return "live"


__all__ = [
    "RECORDED_ORIGINS",
    "ReplyOrigin",
    "ReplyOriginWatch",
    "record_reply_origin",
    "round_trip_origin",
    "watch_reply_origin",
]
