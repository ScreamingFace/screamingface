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
from combine_fields_support import pick_spec, step
from combine_signal_support import argmax_spec, filter_spec
from combine_support import context_text, run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.evidence import ResultRecord
from screamingface_engine.combine.ports import CombineError, Reducer, SpecInvalid
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


_PICK_TEXTS = ['{"confidence": 0.4}', '{"confidence": 0.9}', '{"confidence": 0.7}']


def test_a_hand_written_field_pick_without_extract_abstains_or_fails() -> None:
    # WHY pinned: `pick` allows no extract (argmax), so a hand-written values@1 + by_field@1 spec
    # without one is now accepted. The SDK always writes the extract for a field pick, so only a
    # hand-written spec reaches this. Its "equals" form abstains (before: combine_spec_invalid),
    # and its "max" and "min" forms still fail, because values@1 finds no numeric value.
    equals = pick_spec(3, step("by_field@1", order="equals", value="0.7", normalize="numeric"))
    equals["extract"] = equals["normalize"] = None
    outcome = run(spec_text(equals), context_text(_PICK_TEXTS), registry=BUILTIN_OPERATORS)
    assert outcome.output == ""
    assert outcome.evidence.result == ResultRecord(
        member_id=None, value=None, status="abstain", reason="no_votes"
    )

    for order in ("max", "min"):
        ranked = pick_spec(3, step("by_field@1", order=order))
        ranked["extract"] = ranked["normalize"] = None
        with pytest.raises(CombineError) as caught:
            run(spec_text(ranked), context_text(_PICK_TEXTS), registry=BUILTIN_OPERATORS)
        assert caught.value.code == "combine_spec_invalid"


def test_the_engine_does_not_cross_check_the_two_order_args() -> None:
    # WHY pinned (F3): the select step's order decides the pick, and the signal order in the
    # evidence is the reduce step's. The engine does not compare them: the SDK writes one `order`
    # into both steps (INVARIANT). A cross-check needs a core hook, which is a follow-up.
    spec = argmax_spec(3, "field:s", "max")
    spec["select"] = {"op": "best_holder@1", "args": {"order": "min"}}
    texts = ['{"s": 0.5}', '{"s": 0.9}', '{"s": 0.1}']

    outcome = run(spec_text(spec), context_text(texts), registry=BUILTIN_OPERATORS)

    assert outcome.evidence.chosen == ["member_3"]
    assert outcome.evidence.signal is not None
    assert outcome.evidence.signal.order == "max"
