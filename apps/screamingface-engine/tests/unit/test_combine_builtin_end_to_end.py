"""A vote and a median run end to end through the built-in operators (OME-1289 E4a, unit 2).

FEATURE: deterministic combine of member texts with the real operators, no model call.
STORY: as an author, a majority vote returns the first member's own text byte for byte, and a
median returns the median value as built text.
"""

from __future__ import annotations

from combine_golden_support import builtin_median_spec, builtin_vote_spec
from combine_support import context_text, run, run_recorded, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS

_VOTE_TEXTS = [
    "So the total is 18.",
    "Final: 18",
    "I computed 26 in the end",
    "18",
    "= 18.0",
]
_MEDIAN_TEXTS = ["I think 10", "12 is my answer", "maybe 30", "40 "]


def test_vote_returns_first_holder_text_with_tally_18_to_4_and_26_to_1() -> None:
    intent = spec_text(builtin_vote_spec(5))
    context = context_text(_VOTE_TEXTS)
    outcome = run(intent, context, registry=BUILTIN_OPERATORS)
    assert outcome.output == _VOTE_TEXTS[0]
    evidence = outcome.evidence.model_dump(by_alias=True)
    assert evidence["operators"] == ["last_number@1", "numeric@1", "mode@1", "first_holder@1"]
    assert evidence["tally"] == [
        {"value": "18", "score": 4.0, "holders": ["member_1", "member_2", "member_4", "member_5"]},
        {"value": "26", "score": 1.0, "holders": ["member_3"]},
    ]
    assert [(m["raw"], m["value"], m["status"]) for m in evidence["members"]] == [
        ("18", "18", "answered"),
        ("18", "18", "answered"),
        ("26", "26", "answered"),
        ("18", "18", "answered"),
        ("18.0", "18", "answered"),
    ]
    assert evidence["chosen"] == ["member_1"]
    assert evidence["built"] is False
    assert evidence["agreement"] == 0.8
    assert evidence["tie"] is False
    assert evidence["median"] is None


def test_vote_through_the_url4_route_records_the_same_evidence() -> None:
    output, calls = run_recorded(
        spec_text(builtin_vote_spec(5)), context_text(_VOTE_TEXTS), registry=BUILTIN_OPERATORS
    )
    assert output == _VOTE_TEXTS[0]
    assert len(calls) == 1
    assert calls[0].combine is not None
    assert calls[0].combine.chosen == ["member_1"]


def test_median_value_is_21_built_with_no_chosen_member() -> None:
    spec = builtin_median_spec(4, select_op="value@1")
    outcome = run(spec_text(spec), context_text(_MEDIAN_TEXTS), registry=BUILTIN_OPERATORS)
    assert outcome.output == "21"
    evidence = outcome.evidence.model_dump(by_alias=True)
    assert evidence["kind"] == "answer"
    assert evidence["operators"] == ["last_number@1", "numeric@1", "median@1", "value@1"]
    assert evidence["built"] is True
    assert evidence["chosen"] == []
    assert evidence["median"] == "21"
    assert evidence["tally"] is None
    assert evidence["agreement"] is None
    assert evidence["tie"] is False


def test_median_nearest_picks_the_first_member_at_the_minimum_distance() -> None:
    # 10, 12, 30, 40: median 21; distances 11, 9, 9, 19; two different values tie at 9.
    spec = builtin_median_spec(4)
    outcome = run(spec_text(spec), context_text(_MEDIAN_TEXTS), registry=BUILTIN_OPERATORS)
    assert outcome.output == _MEDIAN_TEXTS[1]
    evidence = outcome.evidence.model_dump(by_alias=True)
    assert (evidence["chosen"], evidence["built"], evidence["tie"]) == (["member_2"], False, True)
    assert evidence["agreement"] == 0.25
