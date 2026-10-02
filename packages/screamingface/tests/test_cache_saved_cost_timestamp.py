"""Accounting assertions must ignore incidental money-like timestamp text."""

from dataclasses import replace
from datetime import datetime

import pytest
import test_cache_saved_cost_submission as accounting


@pytest.mark.parametrize("fraction", ["565488", "500000"])
def test_archive_money_exclusion_with_money_like_timestamp(monkeypatch, fraction):
    timestamp = datetime.fromisoformat(f"2026-10-01T22:00:00.{fraction}+00:00")
    original = accounting._CachedReplayTransport.run

    def timed(self, candidate, on_event):
        return replace(
            original(self, candidate, on_event),
            started_at=timestamp,
            completed_at=timestamp,
        )

    monkeypatch.setattr(accounting._CachedReplayTransport, "run", timed)
    # INVARIANT: exercise the original accounting contract with CI's failing timestamp.
    accounting.test_archive_money_never_reaches_the_result_or_the_board()
