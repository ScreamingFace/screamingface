"""The retry delay of the publish worker (PB-E4).

FEATURE: OME-1307 (E14). INVARIANT: pure, standard library only.
"""

from __future__ import annotations

BASE_S = 60.0
CAP_S = 3600.0
MAX_ATTEMPTS = 8


def next_delay_s(attempts: int, *, retry_after_s: float | None, jitter: float) -> float:
    """Exponential backoff with up to 20 percent jitter, never below `Retry-After`.

    `attempts` is the count AFTER this failure (1 for the first). `jitter` is in [0, 1) and comes
    from the caller's rng.

    INVARIANT: the jitter never pushes the delay below `Retry-After`.
    """
    raw = min(CAP_S, BASE_S * 2 ** (attempts - 1))
    return max(raw * (1 + 0.2 * jitter), retry_after_s or 0.0)
