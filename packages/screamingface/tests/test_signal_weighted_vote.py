"""Signal-weighted sf.Vote: weights on the Median, the block twin, the spec and recovery (OME-1289).

FEATURE: ``sf.Vote(weights=[...] | sf.signal(key))`` and ``sf.Reduce("weighted", ...)`` are one
Candidate (unit 7, BK#4, SR#9).
INVARIANT: ``sf.Median(weights=...)`` raises TypeError, while ``sf.Reduce("median", weights=...)``
raises ValueError ("does not take option"): both rules are pinned (F10).
"""

from __future__ import annotations

import pytest

import screamingface as sf


def test_median_rejects_signal_weights() -> None:
    with pytest.raises(TypeError, match="weights apply to Vote only"):
        sf.Median(weights=sf.signal("cost_usd"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="weights apply to Vote only"):
        sf.Median(weights=[1, 2])  # type: ignore[arg-type]
    assert sf.Median(weights=None).select == "nearest"
    # BK-D1 keeps the block's own rule: a ValueError that names the option (F10).
    with pytest.raises(ValueError, match="does not take option 'weights'"):
        sf.Reduce("median", extract=sf.Extract("last_number"), weights=sf.signal("cost_usd"))
