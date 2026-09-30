"""PB-14 (the delay table) — `next_delay_s`, the retry delay of the publish worker (PB-E4).

FEATURE: OME-1307 (E14). INVARIANT under test: jitter never pushes the delay below Retry-After.
"""

from __future__ import annotations

import pytest

from scoreboard.core.publish.backoff import CAP_S, MAX_ATTEMPTS, next_delay_s


@pytest.mark.parametrize(
    ("attempts", "retry_after", "jitter", "expected"),
    [
        pytest.param(1, None, 0.0, 60.0, id="first"),
        pytest.param(2, None, 0.0, 120.0, id="second"),
        pytest.param(7, None, 0.0, 3600.0, id="capped"),
        pytest.param(8, None, 0.0, 3600.0, id="stays-capped"),
        pytest.param(1, None, 0.5, 66.0, id="jitter-adds-ten-percent"),
        pytest.param(1, None, 0.999, 60.0 * (1 + 0.2 * 0.999), id="jitter-below-twenty-percent"),
        pytest.param(1, 900.0, 0.0, 900.0, id="retry-after-wins"),
        pytest.param(1, 61.0, 0.0, 61.0, id="retry-after-just-above-base"),
        pytest.param(1, 60.0, 0.9, 60.0 * 1.18, id="jitter-may-add-to-retry-after-floor"),
    ],
)
def test_github_5xx_429_backoff_then_failed_after_8_delays(
    attempts: int, retry_after: float | None, jitter: float, expected: float
) -> None:
    assert next_delay_s(attempts, retry_after_s=retry_after, jitter=jitter) == pytest.approx(
        expected
    )


def test_the_cap_and_the_attempt_limit_are_the_plan_values() -> None:
    assert (CAP_S, MAX_ATTEMPTS) == (3600.0, 8)


@pytest.mark.parametrize("jitter", [0.0, 0.3, 0.99])
def test_jitter_never_pushes_the_delay_below_retry_after(jitter: float) -> None:
    # INVARIANT: the server said "not before N seconds"; a smaller delay would be retried too early.
    for attempts in range(1, MAX_ATTEMPTS + 1):
        assert next_delay_s(attempts, retry_after_s=500.0, jitter=jitter) >= 500.0
