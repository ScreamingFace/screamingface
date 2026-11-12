"""E5 P2 spec R1, R4, R7, R10, D9b and D11: the settings of the Engine's driver.

FEATURE: a detached Run (OME-1837).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from screamingface_engine.config import Settings


def test_the_defaults_are_the_specs() -> None:
    settings = Settings()

    assert settings.run_driver_inflight == 8
    assert settings.run_driver_lease_s == 60
    assert settings.run_driver_tick_s == 15
    assert settings.run_outcome_grace_s == 120
    assert settings.run_result_write_budget_s == 60
    assert settings.run_events_poll_s == 1
    assert settings.run_follow_stamp_s == 30
    assert settings.run_context_max_bytes == 4 * 1024**2
    assert settings.run_request_max_bytes == 8 * 1024**2
    assert settings.run_detached_deadline_s == 48 * 3600
    assert settings.run_detached_deadline_max_s == 7 * 86_400
    assert settings.topic_claim_budget_s == 5


@pytest.mark.parametrize(
    ("orphan_grace_s", "run_follow_stamp_s", "expected"),
    [(120, 30, 30), (60, 30, 30), (50, 30, 25), (0.25, 30, 0.125)],
)
def test_a_follower_is_stamped_at_least_twice_per_orphan_grace(
    orphan_grace_s: float, run_follow_stamp_s: float, expected: float
) -> None:
    """INVARIANT (R10): one late stamp must never read as an orphaned Run. WHY derived, not
    refused: a short orphan grace set alone, as P1 allowed, must still start."""
    settings = Settings(orphan_grace_s=orphan_grace_s, run_follow_stamp_s=run_follow_stamp_s)

    assert settings.follow_stamp_s == expected


def test_the_follow_stamp_is_the_setting_with_the_orphan_rule_off() -> None:
    assert Settings(orphan_grace_s=0, run_follow_stamp_s=300).follow_stamp_s == 300


def test_a_default_deadline_past_the_longest_allowed_is_refused() -> None:
    with pytest.raises(ValidationError, match="run_detached_deadline_s"):
        Settings(run_detached_deadline_s=8 * 86_400)


def test_a_context_cap_that_does_not_fit_the_body_is_refused() -> None:
    with pytest.raises(ValidationError, match="run_context_max_bytes"):
        Settings(run_context_max_bytes=8 * 1024**2)


@pytest.mark.parametrize(
    "field",
    [
        "run_driver_inflight",
        "run_driver_lease_s",
        "run_driver_tick_s",
        "run_outcome_grace_s",
        "run_events_poll_s",
        "run_follow_stamp_s",
        "run_context_max_bytes",
        "run_detached_deadline_s",
        "topic_claim_budget_s",
    ],
)
def test_a_non_positive_setting_is_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: 0})
