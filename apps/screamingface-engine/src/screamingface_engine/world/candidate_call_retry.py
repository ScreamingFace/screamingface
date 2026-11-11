"""When a Candidate model call the gateway failed for a moment is asked again, and how long to wait.

FEATURE (OME-1872): a Case's score must reflect the model's answer, never one bad minute at the
AI gateway. The gateway answers 429 when a provider stays busy past its own retries (3 within
30 s), and 5xx when it breaks itself. Before this, the connector marked both temporary but no one
asked a Candidate call again, so the Case failed. Now the connector asks it again, 2 times.

The rule, in the order the connector applies it:

1. Only a Candidate call (the model or Fusion being scored, ``in_candidate_invocation()``)
   retries. A judge already gets 2 re-asks of its own (``judge_redraw.py`` or url4's
   ``;retry=2``); a connector retry on top would give each judge item 3 x 3 = 9 tries.
2. Only a temporary answer retries: 429 or any 5xx, the same statuses the connector marks
   ``permanent=False`` (``connector._raise_for_status``).
3. Retry k waits ``RETRY_WAITS_S[k-1]`` plus up to ``JITTER_S`` of jitter, raised to the
   gateway's ``Retry-After`` when that asks for longer, never more than ``RETRY_AFTER_CAP_S``.

Worked example: a call answered 429 (``Retry-After: 45``), then 502, then 200. Retry 1 waits 45 s
(the hint beats the 10 s schedule); retry 2 waits 30 s; the third try answers, so the Case is
scored on the model's real answer. Had the third try failed too, the Case fails as a temporary
infrastructure failure, exactly as it did before this change.

WHY these waits and not url4's 0.5 s / 1 s backoff: the gateway has already retried a busy
provider for up to 30 s before it answers 429, so a retry one second later meets the same rate
limit. Two retries wait about 40 s at most without a ``Retry-After`` hint.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from typing import Final

#: How many times a Candidate call may be asked AGAIN after a temporary failure. Matches the
#: judges' ``MAX_JUDGE_REDRAWS`` (2), so a Candidate gets the three tries a judge item gets.
CANDIDATE_CALL_RETRIES: Final[int] = 2

#: The wait before retry 1 and retry 2, in seconds.
RETRY_WAITS_S: Final[tuple[float, ...]] = (10.0, 30.0)

#: Up to this much is added to each wait, so Cases rate-limited together do not return together.
JITTER_S: Final[float] = 2.0

#: The longest wait a gateway ``Retry-After`` may ask for, so one header cannot stall a Case.
RETRY_AFTER_CAP_S: Final[float] = 120.0

_TOO_MANY_REQUESTS: Final[int] = 429
_SERVER_ERRORS: Final[range] = range(500, 600)

# Seam, so tests do not depend on the global random state.
_jitter: Callable[[float, float], float] = random.uniform


def is_temporary(status_code: int) -> bool:
    """Whether a gateway answer is a passing failure worth asking again: 429 or any 5xx."""
    return status_code == _TOO_MANY_REQUESTS or status_code in _SERVER_ERRORS


def may_have_billed(status_code: int) -> bool:
    """Whether a failed try may have reached the provider and been charged.

    WHY: the gateway answers 429 only after the provider refused the call, so nothing was billed;
    a 5xx can come after the provider answered (the gateway broke reading the reply).
    """
    return status_code in _SERVER_ERRORS


def retry_wait(retry_number: int, retry_after: str | None) -> float:
    """Seconds to wait before retry ``retry_number`` (1-based), given the gateway's ``Retry-After``.

    A hint that is not a finite, non-negative number of seconds is ignored; a hint shorter than
    the schedule never shortens it.
    """
    scheduled: float = RETRY_WAITS_S[retry_number - 1] + _jitter(0.0, JITTER_S)
    asked: float = _seconds(retry_after)
    return max(scheduled, min(asked, RETRY_AFTER_CAP_S))


def _seconds(retry_after: str | None) -> float:
    """A ``Retry-After`` delta-seconds value, or 0 when absent or unreadable."""
    try:
        seconds: float = float(retry_after or "")
    except ValueError:
        return 0.0
    return seconds if math.isfinite(seconds) and seconds >= 0 else 0.0


__all__ = [
    "CANDIDATE_CALL_RETRIES",
    "JITTER_S",
    "RETRY_AFTER_CAP_S",
    "RETRY_WAITS_S",
    "is_temporary",
    "may_have_billed",
    "retry_wait",
]
