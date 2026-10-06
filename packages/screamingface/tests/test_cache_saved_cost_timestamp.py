"""Accounting assertions must ignore incidental money-like timestamp text."""

from dataclasses import replace
from datetime import datetime

import pytest
import test_cache_saved_cost_submission as accounting

import screamingface as sf


@pytest.mark.parametrize("fraction", ["565488", "500000"])
def test_archive_money_accounting_with_money_like_timestamp(monkeypatch, fraction):
    timestamp = datetime.fromisoformat(f"2026-10-01T22:00:00.{fraction}+00:00")
    original = accounting._CachedReplayTransport.run

    def timed(self, candidate, on_event):
        return replace(
            original(self, candidate, on_event),
            started_at=timestamp,
            completed_at=timestamp,
        )

    monkeypatch.setattr(accounting._CachedReplayTransport, "run", timed)
    # INVARIANT: exercise the current accounting contract with CI's failing timestamp.
    accounting.test_archive_money_reaches_the_result_and_the_board()
    result = accounting._evaluate(accounting._CachedReplayTransport(reported=None, archive="0.500"))
    payload = accounting._submission(result)
    assert payload["run_cost_usd"] is None
    assert payload["run_cost_status"] == "partial"
    exported = result.to_dict()
    assert exported["cache_saved_cost_usd"] is None
    assert exported["cache_saved_cost_archive_usd"] == "0.500"
    assert exported["usage"] == sf.Usage().to_dict()
