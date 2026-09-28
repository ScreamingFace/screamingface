"""Warns a run's attached client, once, when its queued run has not started past a grace.

FEATURE: warn the client about an unclaimed queued run (under OME-1086; the residual gap of
OME-1059 and OME-948, both closed as superseded by the queue design).

STORY: as a researcher whose evaluation was accepted while the runner pool is saturated or down,
I am told my run is queued and has not started, instead of watching heartbeats on a silent
socket for up to 16 hours until the queue finally expires it.

WHY this module exists: a run the App admitted but no worker claims reads `scheduled` for the
whole capability lifetime (`capability_lifetime_s`, ~16h20m). The WS bridge heartbeats, the
stream stays empty, and the only terminal frame (`queue_expired`) is written by a worker that
claims the run AFTER that lifetime. A run that was accepted and is not being honoured yet is
what `notices.warn` exists for — advisory, never a nack.

WHY it fires only on a REAL wait (the lesson of `14982d83`, PR #822): the queue-position notice
told every run on a healthy stack "the queue holds N run(s)" and was removed as noise. A healthy
claim takes seconds (the publish sends a wake-up nudge an idle pull answers at once), so a grace
of minutes means a pool that is saturated or absent — and the text is true for both.

INVARIANTS:

- ADVISORY ONLY. The warner never stops, fails or reschedules a run. A wrong verdict costs a
  missing, early or late WARNING and nothing else. Failing an unclaimed run fast is an OPEN
  owner question (see the spec), deliberately not answered here.
- GENERIC TEXT. Symptom, not cause: no queue depth, pod, bucket, subject or broker name.
- AT MOST ONCE PER RUN. A topic is DECIDED — warned, or seen not `scheduled` — the first time
  its status is read past the grace, and never read again. The decided set is pruned against the
  runner's own record, so it is bounded by the runs accepted within one capability lifetime.
- UNKNOWN IS NOT A VERDICT. An unreadable tail (`QueueReadError`) and a topic with no audience
  decide nothing; the next sweep asks again.

AIDEV-NOTE: POLICY ONLY — no FastAPI, no task ownership, and deliberately no import from `ws`,
like `reaper.py`. The sweep loop lives in `app.py::_install_unclaimed_run_warner`. The registry's
single `AudienceListener` slot stays the reaper's: this module POLLS `has_subscriber` instead.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from screamingface_engine import notices
from screamingface_engine.adapters.jetstream import QueueReadError
from url4.streaming.interfaces import JobStatus
from url4.streaming.protocol import OutboundFrame

_logger = logging.getLogger(__name__)

_MIN_TICK_S = 1.0
_TICKS_PER_GRACE = 8
"""Sweeps per grace window. WHY derived rather than a second setting: warn latency is `grace` to
`grace + grace/8`, one knob with a bounded overshoot — the same rule as the reaper's."""

UNCLAIMED_MESSAGE = "the runner service is at capacity; your run is queued and has not started yet"
"""The user-facing notice body. INVARIANT: no internals — see the module docstring."""

FrameClock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@runtime_checkable
class QueuedRuns(Protocol):
    """The two runner questions the warner needs, and deliberately nothing else.

    `QueueJobRunner` satisfies this structurally. The in-process runner does not (it has no
    queue to wait in), which is how the composition root knows not to install the warner.
    """

    def accepted_ages(self) -> dict[str, float]: ...

    async def status(self, topic: str) -> JobStatus: ...


class NoticeAudience(Protocol):
    """The registry-shaped collaborator: who is listening, and where a notice goes.

    INVARIANT: the REAL `ConnectionRegistry`, never the `interest` DI seam — same rule as the
    reaper. A notice can only reach a connection the registry holds anyway.
    """

    async def has_subscriber(self, topic: str) -> bool: ...

    def notify(self, topic: str, frame: OutboundFrame) -> None: ...


class UnclaimedRunWarner:
    """Sends one WARN to each attached topic whose run is still `scheduled` past the grace."""

    def __init__(
        self,
        runs: QueuedRuns,
        audience: NoticeAudience,
        *,
        grace_s: float,
        frame_clock: FrameClock = _utc_now,
        tick_s: float | None = None,
    ) -> None:
        self._runs = runs
        self._audience = audience
        self._grace_s = grace_s
        self._frame_clock = frame_clock
        self._tick_s = (
            tick_s if tick_s is not None else max(_MIN_TICK_S, grace_s / _TICKS_PER_GRACE)
        )
        self._decided: set[str] = set()
        self._warned_total = 0

    @property
    def tick_s(self) -> float:
        """Seconds between sweeps. The loop in `app.py` reads its cadence from here."""
        return self._tick_s

    @property
    def decided_count(self) -> int:
        """Topics whose verdict is final (warned or seen started) and still remembered."""
        return len(self._decided)

    @property
    def warned_total(self) -> int:
        """Runs warned as unclaimed, since boot."""
        return self._warned_total

    async def sweep(self) -> tuple[str, ...]:
        """Warn every undecided, attached topic whose run is still `scheduled` past the grace;
        return the topics warned.

        Split from the loop that calls it so tests drive the policy with no sleeps.
        """
        ages = self._runs.accepted_ages()
        # Bounded by the runner's record: a topic the runner forgot (capability expiry) is
        # forgotten here too.
        self._decided &= ages.keys()
        warned: list[str] = []
        for topic, age in ages.items():
            if age < self._grace_s or topic in self._decided:
                continue
            if await self._warn_if_unclaimed(topic, age):
                warned.append(topic)
        return tuple(warned)

    async def _status_if_heard(self, topic: str) -> JobStatus | None:
        """The run's status, or ``None`` when the answer would decide nothing: nobody is
        attached, or the stream tail is unreadable (UNKNOWN, not a verdict)."""
        # WHY the audience first: it is an in-process dict read, and a topic nobody is
        # watching costs no broker read. It is NOT decided — a reconnect may still need telling.
        if not await self._audience.has_subscriber(topic):
            return None
        try:
            return await self._runs.status(topic)
        except QueueReadError:
            _logger.warning("unclaimed-run check: stream tail unreadable topic=%s", topic)
            return None

    async def _warn_if_unclaimed(self, topic: str, age: float) -> bool:
        """Decide one topic past the grace; ``True`` when it was warned."""
        status = await self._status_if_heard(topic)
        if status is None:
            return False
        # INVARIANT: decided BEFORE the notify, and for every readable answer. Any frame on the
        # stream reads non-`scheduled` (the run started), and that verdict is final.
        self._decided.add(topic)
        if status != "scheduled":
            return False
        # AIDEV-NOTE: accepted race — a run claimed between the read above and this notify gets
        # the notice just before its StartedEvent. The window is one broker round trip.
        self._audience.notify(
            topic,
            notices.warn(topic, self._frame_clock, UNCLAIMED_MESSAGE, {"run.wait_s": int(age)}),
        )
        self._warned_total += 1
        _logger.info("unclaimed run warned topic=%s wait_s=%.0f", topic, age)
        return True


__all__ = ["UNCLAIMED_MESSAGE", "NoticeAudience", "QueuedRuns", "UnclaimedRunWarner"]
