"""A ``field:<path>`` key in ``by=`` or ``weights=`` gets the path check of ``sf.field()``.

FEATURE (7d product gap c): ``sf.Rank(k, by="field:<path>")``, ``sf.ArgMax`` / ``sf.ArgMin`` and
``weights="field:<path>"`` refuse a path longer than 256 characters when the step is built, with
the message of ``sf.field()``, and not after the member calls are paid.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

import screamingface as sf

_LONG = "a" * 257


def _rule(label: str) -> str:
    return re.escape(
        f"{label} field path {_LONG!r} must be a JSON path like 'score', 'a.b' or 'a[0].b' "
        "(at most 256 characters)"
    )


@pytest.mark.parametrize(
    ("build", "label"),
    [
        (lambda key: sf.Rank(2, by=key), "sf.Rank"),
        (lambda key: sf.ArgMax(key), "sf.ArgMax"),
        (lambda key: sf.ArgMin(sf.signal(key)), "sf.ArgMin"),
        (lambda key: sf.Vote(weights=key), "Vote weights"),
        (lambda key: sf.Median(weights=sf.signal(key)), "Median weights"),
        (lambda key: sf.Mean(weights=key), "Mean weights"),
    ],
    ids=["rank", "argmax", "argmin-signal", "vote-weights", "median-weights", "mean-weights"],
)
def test_a_field_key_longer_than_256_characters_is_refused(
    build: Callable[[str], object], label: str
) -> None:
    with pytest.raises(ValueError, match=f"^{_rule(label)}$"):
        build(f"field:{_LONG}")
    # the longest path passes, as in sf.field()
    build("field:" + "a" * 256)
    sf.field("a" * 256)
