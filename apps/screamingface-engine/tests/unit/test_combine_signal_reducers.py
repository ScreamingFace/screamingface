"""The filter reducer exists and pick runs without an extract (OME-1289 E4a gap-closure, unit 10E).

FEATURE: argmax compiles to ``pick`` with no extract step, and a filter has its own reducer name.
STORY: as an author, a pick over a signal and a filter over members are valid specs, and a bad
weights block on a filter is refused at spec check.
INVARIANT defended: ``REDUCER_RULES`` names exactly the ``Reducer`` values; units 8 to 10 only
loosen or tighten the presence rows of their own reducers and add no operator rule.
"""

from __future__ import annotations

from typing import get_args

import pytest
from combine_signal_support import argmax_spec, filter_spec
from combine_support import spec_text

from screamingface_engine.combine.ports import Reducer, SpecInvalid
from screamingface_engine.combine.spec import REDUCER_RULES, parse_spec

_THRESHOLD = {"key": "field:confidence", "cmp": "ge", "value": 0.6}
_EXTRACT = {"op": "json_field@1", "args": {"path": "answer"}}


def test_reducer_rules_cover_every_reducer() -> None:
    assert set(REDUCER_RULES) == set(get_args(Reducer))
    assert "filter" in get_args(Reducer)


def test_filter_reducer_rules() -> None:
    assert REDUCER_RULES["filter"].kind == "selection"

    assert parse_spec(spec_text(filter_spec(3, _THRESHOLD))).reducer == "filter"
    assert parse_spec(spec_text(filter_spec(3, _THRESHOLD, _EXTRACT))).extract is not None

    weighted = filter_spec(3, _THRESHOLD)
    weighted["weights"] = {"member_1": 1.0, "member_2": 1.0, "member_3": 1.0}
    with pytest.raises(SpecInvalid, match="forbids weights"):
        parse_spec(spec_text(weighted))


def test_pick_takes_an_optional_extract() -> None:
    parsed = parse_spec(spec_text(argmax_spec(3, "cost_usd", "min")))
    assert (parsed.reducer, parsed.extract, parsed.normalize) == ("pick", None, None)

    pick_field = argmax_spec(3, "cost_usd", "min")
    pick_field["extract"] = {"op": "json_field@1", "args": {"path": "answer"}}
    assert parse_spec(spec_text(pick_field)).extract is not None
