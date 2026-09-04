"""Stops runs whose audience has gone and not come back.

FEATURE: tie a run's lifetime to its audience (OME-890).

STORY: as a researcher whose notebook kernel died mid-evaluation, I do not keep paying for a run
nobody can receive, and the next evaluation gets its concurrency slot back.

WHY this module exists: the 428 gate (`rest/routes.py::_require_subscriber`) proves an audience
exists when a run starts, and then nothing ever asks again. A client that dies before it can send
`ai.url4.stop` — `kill -9`, a Jupyter kernel restart, laptop sleep, a network partition — leaves
the run issuing paid model calls until `job_deadline_s` (16h), holding one of
`local_max_concurrent_runs` slots and the gateway's per-provider slots the whole time. This
closes the loop: the audience leaving arms a grace window, the audience returning disarms it, and
expiry stops the run through the same idempotent `JobRunner.stop` the explicit paths use.

AIDEV-NOTE: POLICY ONLY — no FastAPI, no task ownership, and deliberately no import from `ws`.
The sweep loop lives in `app.py::_install_orphan_reaper`, beside the artifact sweeper it is
modelled on. The registry's `AudienceListener` is satisfied structurally, which is what keeps
these two modules decoupled.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

_logger = logging.getLogger(__name__)

_MIN_TICK_S = 1.0
_TICKS_PER_GRACE = 8
"""How many sweeps fit inside one grace window. WHY derived rather than a second setting: reap
latency is `grace` to `grace + grace/8`, so an operator tunes ONE knob and gets a bounded
overshoot, instead of two knobs that can be set into disagreement."""


class Audience(Protocol):
    """The subscriber question, as `ConnectionRegistry` answers it."""

    async def has_subscriber(self, topic: str) -> bool: ...


class RunControl(Protocol):
    """The two things the reaper needs from a job runner, and deliberately nothing else.

    WHY a narrow Protocol instead of the `JobRunner` ABC: reaping reads liveness and cancels. It
    has no business scheduling a run or closing the runner, and declaring the whole ABC would say
    it might. `IdentityAwareJobRunner` satisfies this structurally, so the composition root passes
    the real runner unchanged.
    """

    async def exists(self, topic: str) -> bool: ...

    async def stop(self, topic: str) -> None: ...


class RunReaper:
    """Arms a grace window when a topic's audience empties; stops the run if it stays empty.

    INVARIANT: `audience` is the REAL `ConnectionRegistry` — never the `SubscriberGate` DI seam.
    `DenyAllGate` and the tests' `FixedGate(False)` answer "nobody is listening" for EVERY topic.
    That is harmless as an admission gate, where the result is a visible refused start, and
    catastrophic here, where it means "stop every run in this process". Same call as
    `rest/routes.py::_deps` taking `registry` over `interest` for session state.

    INVARIANT: deadlines are monotonic. A wall clock would let an NTP step or a suspend jump
    expire a window that has not elapsed, and reap a live run.
    """

    def __init__(
        self,
        job_runner: RunControl,
        audience: Audience,
        *,
        grace_s: float,
        clock: Callable[[], float] = time.monotonic,
        tick_s: float | None = None,
    ) -> None:
        self._job_runner = job_runner
        self._audience = audience
        self._grace_s = grace_s
        self._clock = clock
        self._tick_s = (
            tick_s if tick_s is not None else max(_MIN_TICK_S, grace_s / _TICKS_PER_GRACE)
        )
        self._deadlines: dict[str, float] = {}
        self._reaped_total = 0

    @property
    def tick_s(self) -> float:
        """Seconds between sweeps. The loop in `app.py` reads its cadence from here."""
        return self._tick_s

    @property
    def armed_count(self) -> int:
        """Topics currently inside a grace window.

        WHY exposed: it is the `/metrics` gauge, and a value that never returns to zero is how an
        operator sees that sweeps have stopped running — a silently dead reaper otherwise looks
        exactly like "no orphans happened".
        """
        return len(self._deadlines)

    @property
    def reaped_total(self) -> int:
        """Runs stopped for having no audience, since boot."""
        return self._reaped_total

    def is_armed(self, topic: str) -> bool:
        """Whether ``topic`` is inside a grace window."""
        return topic in self._deadlines

    # --- AudienceListener (satisfied structurally; see ws.registry.AudienceListener) ---

    def audience_left(self, topic: str) -> None:
        """Arm: ``topic`` has until now + grace to get its audience back."""
        self._deadlines[topic] = self._clock() + self._grace_s

    def audience_arrived(self, topic: str) -> None:
        """Disarm: somebody is listening again."""
        self._deadlines.pop(topic, None)

    async def sweep(self) -> tuple[str, ...]:
        """Stop every armed run whose grace window has closed; return the topics stopped.

        Split from the loop that calls it so tests drive the policy against an injected clock
        with no sleeps at all.
        """
        now = self._clock()
        due = [topic for topic, deadline in self._deadlines.items() if now >= deadline]
        reaped: list[str] = []
        for topic in due:
            if await self._reap(topic, now):
                reaped.append(topic)
        return tuple(reaped)

    async def _reap(self, topic: str, now: float) -> bool:
        """Stop one expired topic's run; ``True`` when it was actually stopped.

        AIDEV-NOTE: this stays within ruff's `max-returns = 3`. The two guards share one `or`
        deliberately — do not split them into separate `return False` branches.
        """
        # INVARIANT: the topic is CLAIMED — popped — before the first `await`. On a
        # single-threaded loop that makes "this window closed and it is mine to decide" one
        # atomic step, so a reconnect cannot land between the check and the claim. One arriving
        # afterwards simply finds nothing armed, which is the same end state as a disarm.
        self._deadlines.pop(topic, None)
        try:
            # First guard: the audience came back and the disarm was missed or raced.
            # Second guard: the run is already terminal. `stop` is idempotent, but on the k8s runner
            # it DELETEs the Job, which would drop a finished Job before the TTL that is its
            # single-use replay guard. The order matters: an in-process dict lookup short-circuits
            # ahead of a possible Kubernetes API call.
            #
            # WHY both guards sit under the try (review follow-up P2-10): `exists` raises
            # `QueueReadError` on a transient broker failure, and the pop above already
            # CLAIMED the topic — an unguarded raise aborted the sweep with the deadline
            # gone and nothing left to re-arm it: the orphan was silently forgotten and
            # ran to the 16h ceiling, the exact spend this module exists to prevent. A
            # failure here re-arms like a failed stop below.
            if not await self._still_armed(topic):
                return False
            await self._job_runner.stop(topic)
        except Exception:
            # INVARIANT: a failed action RE-ARMS rather than gives up, without bound. Abandoning
            # the topic would hand the run back to the 16h ceiling, which is the exact spend this
            # module exists to prevent; the per-tick warning is the operator's signal that the
            # runner itself needs attention.
            self._deadlines[topic] = now + self._tick_s
            _logger.warning("orphan reap failed topic=%s; will retry", topic, exc_info=True)
            return False
        self._reaped_total += 1
        _logger.info(
            "orphan run reaped topic=%s reason=no_subscriber grace_s=%.0f",
            topic,
            self._grace_s,
        )
        return True

    async def _still_armed(self, topic: str) -> bool:
        """Whether the expired topic still deserves a reap: nobody is listening AND the run
        is live.

        The audience lookup is an in-process dict read and short-circuits the `exists`
        call (a broker RPC on the queue runner), so an audience that returned costs no
        RPC. `exists` raises `QueueReadError` on a transient broker failure — that raise
        is caught by `_reap`'s guard try, which re-arms the deadline.
        """
        if await self._audience.has_subscriber(topic):
            return False
        return await self._job_runner.exists(topic)
