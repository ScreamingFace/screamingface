"""A ``field:<path>`` key in ``by=`` or ``weights=`` gets the path check of ``sf.field()``.

FEATURE (7d product gap c): ``sf.Rank(k, by="field:<path>")``, ``sf.ArgMax`` / ``sf.ArgMin`` and
``weights="field:<path>"`` refuse a path longer than 256 characters when the step is built, with
the message of ``sf.field()``. The Engine has no such cap; the SDK refuses the path before the
compile so that every public value that carries a field path has the same rule: ``over=
"field:<path>"``, ``sf.Extract("field", path=...)`` and ``sf.Filter(where=sf.signal("field:<path>")
>= x)`` too.
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
        (lambda key: sf.Vote(weights=key), "sf.Vote weights"),
        (lambda key: sf.Median(weights=sf.signal(key)), "sf.Median weights"),
        (lambda key: sf.Mean(weights=key), "sf.Mean weights"),
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


@pytest.mark.parametrize(
    ("build", "label"),
    [
        (lambda key: sf.Median(over=key), "over="),
        (
            lambda key: sf.Filter(where=sf.signal(key) >= 0.5),
            "sf.Filter where=",
        ),
    ],
    ids=["over", "filter-where"],
)
def test_every_public_field_path_has_the_256_character_rule(
    build: Callable[[str], object], label: str
) -> None:
    with pytest.raises(ValueError, match=f"^{_rule(label)}$"):
        build(f"field:{_LONG}")
    build("field:" + "a" * 256)


def test_an_extract_field_path_has_the_256_character_rule() -> None:
    with pytest.raises(ValueError) as caught:
        sf.Extract("field", path=_LONG)
    assert str(caught.value) == (
        f"sf.Extract('field') path {_LONG!r} must be a JSON path like 'score', 'a.b' or 'a[0].b' "
        "(at most 256 characters)"
    )
    sf.Extract("field", path="a" * 256)
