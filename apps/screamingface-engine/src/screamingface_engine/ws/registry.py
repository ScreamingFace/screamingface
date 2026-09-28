"""In-process, per-topic WebSocket session state: how many connections are attached, what cache
policy the first of them declared, and where to reach them with a notice.

All three live on one record deliberately. A declaration is only load-bearing between the first
attach and the moment the run is scheduled — ``_require_subscriber`` refuses to schedule a run
with nothing attached, so that window is entirely contained inside "this topic has a subscriber",
and the runner captures the policy at schedule time. Binding the declaration's lifetime to the
subscriber count therefore costs nothing that can affect a run, and buys a store bounded by live
connections instead of one that grows by a row per topic the process has ever seen.

The same invariant is what makes the notice channel deliverable rather than best-effort: the REST
route can only override a frame's declaration on a request that already passed the 428 gate, so a
socket for the topic is attached, in THIS process, at exactly that moment. The App never publishes
to the broker — it schedules runs and reads their log — so routing a notice through the attached
connection is the only path that does not change that posture.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Protocol

from url4.streaming.protocol import CachePolicy, OutboundFrame

Notify = Callable[[OutboundFrame], None]
"""How one live connection accepts an out-of-band frame. Synchronous and non-blocking by
contract: it is called from a request handler, so it hands the frame to that connection's own
outbound queue and returns — it must never await the socket."""


class AudienceListener(Protocol):
    """Where the registry announces a topic's audience arriving and leaving.

    FEATURE: tie a run's lifetime to its audience (OME-890). The 428 gate proves an audience
    exists when a run is scheduled and then nothing asks again, so these two edges are what let
    anything downstream react to "my last subscriber vanished".

    INVARIANT: both methods are synchronous and must not raise. They run inside `add`/`remove`,
    and `remove` runs in the WS endpoint's `finally` — a path that also executes under
    cancellation, where an exception would mask the very disconnect it is reporting.
    """

    def audience_arrived(self, topic: str) -> None:
        """``topic`` went from no subscribers to one."""

    def audience_left(self, topic: str) -> None:
        """``topic``'s last subscriber disconnected."""


@dataclass
class _Session:
    """One topic's session: its audience (live WS connections and waiting sync requests), the
    cache intent the connections declared, and their sinks."""

    subscribers: int = 0
    """Live WebSocket connections."""
    sync_holders: int = 0
    """Sync `GET /?q=` requests waiting for this run's terminal frame (uniform executor PRD 02).
    A waiting caller IS an audience: it reads the result, so the run must not be reaped."""
    cache: CachePolicy | None = None
    cache_declared: bool = False
    """Whether ANY attach has spoken yet. Distinct from ``cache is None`` on purpose: an attach
    frame carrying no policy still declares — it fixes the run under the default — so without this
    flag a later attach could retroactively opt out a run that had already started."""
    notifiers: list[Notify] = field(default_factory=list)
    """One sink per live connection on this topic. A list and not a single slot because two
    sockets may legitimately observe one run, and a notice about the run belongs to both."""


def _audience_of(session: _Session) -> int:
    return session.subscribers + session.sync_holders


class ConnectionRegistry:
    """Tracks each topic's live WS connections and its first-attach cache declaration.

    Counts, rather than sets of connection ids, so concurrent connections on the same topic are
    supported without the endpoint having to hand back a token.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._audience: AudienceListener | None = None

    def listen(self, audience: AudienceListener) -> None:
        """Register the one listener for audience transitions — COMPOSITION ROOT ONLY.

        A setter rather than a constructor argument because the registry is built before the
        reaper that watches it, and the reaper needs the registry (`app.py::create_app`).
        """
        self._audience = audience

    def add(self, topic: str) -> None:
        session = self._sessions.setdefault(topic, _Session())
        session.subscribers += 1
        self._arrived(topic, session)

    def remove(self, topic: str) -> None:
        session = self._sessions.get(topic)
        if session is None:
            return
        session.subscribers -= 1
        self._left(topic, session)

    @asynccontextmanager
    async def hold_sync(self, topic: str) -> AsyncIterator[None]:
        """Count a waiting sync request as `topic`'s audience for the duration of the block.

        WHY an audience and not a bypass of the gate: the 428 gate and the orphan reaper ask the
        same question — "is anybody reading this run?" — and a sync caller is. Held, the gate
        passes and the reaper stays disarmed; released (terminal frame, bound, disconnect, or an
        error — the `finally`), the reaper's grace starts exactly as when a WS leaves.
        """
        session = self._sessions.setdefault(topic, _Session())
        session.sync_holders += 1
        self._arrived(topic, session)
        try:
            yield
        finally:
            session.sync_holders -= 1
            self._left(topic, session)

    @property
    def sync_holders(self) -> int:
        """How many sync requests hold a topic right now, across all topics (a gauge)."""
        return sum(session.sync_holders for session in self._sessions.values())

    def _arrived(self, topic: str, session: _Session) -> None:
        # INVARIANT: 0->1 of the WHOLE audience ONLY. `add_notifier` can create a session at zero,
        # and a second watcher — a WS joining a sync caller, or the reverse — must not read as
        # "the audience arrived".
        if _audience_of(session) == 1 and self._audience is not None:
            self._audience.audience_arrived(topic)

    def _left(self, topic: str, session: _Session) -> None:
        if _audience_of(session) > 0:
            return
        # The session object may already be gone (a WS `remove` past zero); only drop the
        # one that is still registered.
        if self._sessions.get(topic) is session:
            del self._sessions[topic]
        # INVARIANT: 1->0 ONLY, and announced AFTER the session is discarded, so a listener
        # that asks `has_subscriber` from inside the callback gets the post-transition answer.
        if self._audience is not None:
            self._audience.audience_left(topic)

    async def has_subscriber(self, topic: str) -> bool:
        session = self._sessions.get(topic)
        return session is not None and _audience_of(session) > 0

    def declare_cache_policy(self, topic: str, policy: CachePolicy | None) -> bool:
        """Record ``policy`` as ``topic``'s cache intent — FIRST ATTACH WINS (spec §5.2).

        Args:
            topic: The run's topic.
            policy: What this attach frame declared; ``None`` when it declared nothing.

        Returns:
            ``True`` when the topic's standing intent now equals ``policy`` — either because this
            call recorded it, or because the call merely restated what was already recorded (an
            ordinary reconnect re-sending its frame, which must not be reported as anything).
            ``False`` when an intent was already recorded and this one DIFFERS: the standing one
            is left untouched and the caller is expected to say so.

        A run's aigateway calls may already have executed under the recorded intent, so letting a
        re-attach change it would make the run's cache behaviour unreproducible — the reason the
        answer is "ignored and reported" rather than "last writer wins".
        """
        session = self._sessions.setdefault(topic, _Session())
        if session.cache_declared:
            return session.cache == policy
        session.cache_declared = True
        session.cache = policy
        return True

    def cache_policy_for(self, topic: str) -> CachePolicy | None:
        """``topic``'s declared cache intent, or ``None`` if nothing was declared for it.

        ``None`` is deliberately the answer to both "no attach has spoken" and "an attach declared
        nothing": neither states an intent, and both resolve to the default at convergence. What
        the two must NOT be confused with is an explicit opt-out, and that is a policy, not
        ``None``.
        """
        session = self._sessions.get(topic)
        return session.cache if session is not None else None

    def add_notifier(self, topic: str, notify: Notify) -> None:
        """Register one connection's sink for out-of-band frames on ``topic``."""
        self._sessions.setdefault(topic, _Session()).notifiers.append(notify)

    def remove_notifier(self, topic: str, notify: Notify) -> None:
        """Drop a sink registered by :meth:`add_notifier`; a stale one is not an error.

        Idempotent on purpose: the connection that registered it unregisters in a ``finally``,
        which also runs on the path where the last ``remove`` already discarded the whole session.
        """
        session = self._sessions.get(topic)
        if session is not None and notify in session.notifiers:
            session.notifiers.remove(notify)

    def notify(self, topic: str, frame: OutboundFrame) -> None:
        """Offer ``frame`` to every connection attached to ``topic``.

        Best-effort by design, and silent about a topic nobody is listening to: a notice explains
        something about a request that has ALREADY been accepted, so failing the request because
        the explanation could not be delivered would trade a real answer for a footnote. The sinks
        are copied before iterating — a sink is free to drop the frame, and nothing here should
        depend on the list surviving the call.
        """
        session = self._sessions.get(topic)
        if session is None:
            return
        for notify in list(session.notifiers):
            notify(frame)
