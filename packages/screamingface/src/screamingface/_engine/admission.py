"""How long to wait for a run start that the Engine did not admit (OME-1066).

FEATURE: OME-1066 — the Engine refuses a start with `503` + `Retry-After` when it has no
free run capacity (queue depth and per-caller cap, OME-1091). Nothing was scheduled, so the
same start may be sent again (spec 2026-09-28 sdk-run-isolation, E3). This policy turns that
refusal into a bounded wait. Both transport twins share it, so they cannot drift.

WHY here and not in `_core.retry`: that transport retries only requests marked
`_REPLAY_SAFE`, and `GET /?q=` deliberately is not — a start is not replay-safe in general.
Only the start call site knows that THIS answer (503 on start) means "not admitted".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from screamingface._core.retry import _Clock, _retry_after_seconds, _utc_now

# WHY 15 minutes: a queued Run may legitimately wait behind a whole Evaluation (a run can
# take many minutes), but an unbounded wait is indistinguishable from a hang. The default is
# the spec's recommendation and an open owner question (spec 2026-09-28 Q4).
_ADMISSION_BUDGET_S = 900.0


@dataclass
class _AdmissionWait:
    """One Run start's wait for capacity: the delay before each resend, and the deadline.

    INVARIANT: the total wait never passes `budget_s`, counted from the first refusal; the
    last wait is cut to the time left, so the final attempt goes out at the deadline.
    """

    budget_s: float
    # The smallest wait between two attempts — a `Retry-After: 0` must not become a hot loop.
    floor_s: float
    # The fallback when the Engine names no usable `Retry-After` (attempt number → seconds).
    backoff: Callable[[int], float]
    # The clock an HTTP-date `Retry-After` is measured against. Distinct from `next_delay`'s
    # monotonic `now`, which times the budget; this one names an instant on the calendar.
    # WHY injectable (OME-1507): see `_retry_after_seconds`. Production never sets it.
    wall_clock: _Clock = _utc_now
    attempts: int = 0
    _first_refusal: float | None = field(default=None, init=False)

    def next_delay(self, response: httpx.Response, *, now: float) -> float | None:
        """Seconds to wait before the next start attempt, or None when the budget is spent."""
        if self._first_refusal is None:
            self._first_refusal = now
        remaining = self._first_refusal + self.budget_s - now
        if remaining <= 0:
            return None
        # WHY obey the Engine verbatim: its value is a drain estimate (OME-1091); retrying
        # sooner only spends a request against a queue that said it is still full.
        requested = _retry_after_seconds(response, now=self.wall_clock)
        delay = self.backoff(self.attempts) if requested is None else requested
        self.attempts += 1
        return min(max(delay, self.floor_s), remaining)

    def waited_s(self, *, now: float) -> float:
        """How long this start has waited since its first refusal."""
        return 0.0 if self._first_refusal is None else now - self._first_refusal


__all__: list[str] = []
