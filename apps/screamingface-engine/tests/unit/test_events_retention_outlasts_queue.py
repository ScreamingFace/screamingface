"""E5 P1 spec D12: the events stream keeps a cancel's tombstone for as long as the queue can
still start the run it stops (OME-1785).

FEATURE: first-class Runs. STORY: as an operator, a retention setting that would let a canceled
run execute refuses to start instead of failing silently.
"""

from __future__ import annotations

import pytest

from screamingface_engine.config import Settings


def test_the_default_retention_outlasts_a_runnable_queued_run() -> None:
    settings = Settings()

    assert settings.events_max_age_s > min(settings.job_deadline_s, settings.run_queue_max_age_s)


def test_a_retention_shorter_than_a_runnable_queued_run_is_refused() -> None:
    with pytest.raises(ValueError, match="events_max_age_s"):
        Settings(events_max_age_s=3600)


def test_a_short_retention_is_accepted_when_runs_end_sooner() -> None:
    assert Settings(events_max_age_s=3600, job_deadline_s=1800).events_max_age_s == 3600
