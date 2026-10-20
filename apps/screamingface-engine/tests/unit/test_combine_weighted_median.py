"""The weighted median picks the value past half the weight; a dropped member never wins (E4b).

FEATURE: ``weighted_median@1`` gives the middle value of the members with a usable weight; equal
weights give the plain median, and a dropped member never becomes the nearest pick.
STORY: as an author of a robust Candidate, I give trusted members more say, and a member with no
usable weight does not vote at all.
INVARIANT: at exactly half the weight the result is the mean of the two neighbors (P3); the result
does not depend on the author order of equal values; ``median@1`` ignores weights.
"""

from __future__ import annotations

import json
import random

import pytest
from combine_golden_support import (
    FIXTURE_DIR,
    builtin_median_spec,
    combine_input,
    find,
    member_readings,
    reduce_result,
    run_case,
    select_result,
)
from combine_support import context_text, run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.operators.reduce import weighted_median
from screamingface_engine.combine.ports import NoVotes, SpecInvalid, canonical_decimal


def test_median_even_count_is_the_mean_of_the_middle_two() -> None:
    statistic = reduce_result("median@1", member_readings(["90", "10", "60", "20"])).statistic
    assert statistic is not None
    assert canonical_decimal(statistic) == "40"
    two = reduce_result("median@1", member_readings(["2", "1"])).statistic
    assert two is not None
    assert canonical_decimal(two) == "1.5"


def test_weighted_median_takes_the_first_value_past_half_the_weight() -> None:
    readings = member_readings(["10", "20", "60"], weights=["1", "1", "3"])
    statistic = weighted_median(combine_input(readings), {}).statistic
    assert statistic is not None
    assert canonical_decimal(statistic) == "60"


def test_weighted_median_at_exactly_half_is_the_mean_of_neighbors() -> None:
    readings = member_readings(["10", "20", "60"], weights=["1", "1", "2"])
    statistic = weighted_median(combine_input(readings), {}).statistic
    assert statistic is not None
    assert canonical_decimal(statistic) == "40"


def test_weighted_median_nearest_never_picks_a_dropped_member() -> None:
    readings = member_readings(
        ["30", "50", "40"],
        weights=["1", "1", None],
        signals=[{"field:confidence": 1.0}, {"field:confidence": 1.0}, {"field:confidence": 0.0}],
    )
    reduction = weighted_median(combine_input(readings), {})
    assert reduction.statistic is not None
    assert canonical_decimal(reduction.statistic) == "40"
    assert reduction.participants == ("member_1", "member_2")
    selection = select_result("nearest@1", reduction, readings)
    assert selection.chosen == ("member_1",)
    assert selection.tie is True
    assert "member_3" not in selection.chosen


def test_weighted_median_with_equal_weights_equals_median() -> None:
    for values, weight, expected in (
        (["10", "20", "60"], "2", "20"),
        (["10", "20", "60", "90"], "0.5", "40"),
    ):
        readings = member_readings(values, weights=[weight] * len(values))
        statistic = weighted_median(combine_input(readings), {}).statistic
        assert statistic is not None
        assert canonical_decimal(statistic) == expected

    rng = random.Random(20261013)
    for _ in range(300):
        count = rng.randint(1, 9)
        values = [str(rng.randint(-100, 100)) for _ in range(count)]
        weight = rng.choice(["1", "0.5", "7"])
        readings = member_readings(values, weights=[weight] * count)
        weighted = weighted_median(combine_input(readings), {}).statistic
        plain = reduce_result("median@1", member_readings(values)).statistic
        assert weighted is not None and plain is not None
        assert canonical_decimal(weighted) == canonical_decimal(plain)


def test_weighted_median_drops_members_with_no_usable_weight() -> None:
    readings = member_readings(
        ["10", "20", "60", "90"],
        weights=["1", None, None, "3"],
        signals=[
            {"field:c": 1.0},
            {"field:c": None},
            {"field:c": -2.0},
            {"field:c": 3.0},
        ],
    )
    reduction = weighted_median(combine_input(readings), {})
    assert reduction.statistic is not None
    assert canonical_decimal(reduction.statistic) == "90"
    assert reduction.participants == ("member_1", "member_4")


def test_weighted_median_with_no_usable_member_raises_no_votes() -> None:
    readings = member_readings(
        ["10", "20"],
        weights=[None, None],
        signals=[{"field:c": None}, {"field:c": 0.0}],
    )
    with pytest.raises(NoVotes) as caught:
        weighted_median(combine_input(readings), {})
    assert caught.value.reason == "no_votes"


def test_weighted_median_without_spec_weights_is_spec_invalid() -> None:
    readings = member_readings(["10", "20"])
    with pytest.raises(SpecInvalid, match="weighted_median@1 needs weights"):
        weighted_median(combine_input(readings), {})


def test_median_spec_with_weights_ignores_them() -> None:
    spec = builtin_median_spec(3, "value@1")
    spec["weights"] = {"member_1": 1.0, "member_2": 1.0, "member_3": 5.0}
    outcome = run(
        spec_text(spec),
        context_text(["10", "20", "60"]),
        registry=BUILTIN_OPERATORS,
    )
    assert outcome.output == "20"
    assert outcome.evidence.median == "20"


def test_weighted_median_ignores_the_order_of_duplicates() -> None:
    fixed = member_readings(["10", "20", "20", "30"], weights=["1", "1", "2", "4"])
    swapped = member_readings(["10", "20", "20", "30"], weights=["1", "2", "1", "4"])
    for readings in (fixed, swapped):
        statistic = weighted_median(combine_input(readings), {}).statistic
        assert statistic is not None
        assert canonical_decimal(statistic) == "25"

    rng = random.Random(1309)
    for _ in range(300):
        count = rng.randint(2, 8)
        values = [rng.choice(["-5", "0", "3", "3", "7", "7", "7", "12"]) for _ in range(count)]
        weights = [rng.choice(["0.5", "1", "2", "3"]) for _ in range(count)]
        before = weighted_median(combine_input(member_readings(values, weights)), {}).statistic
        pairs = list(zip(values, weights, strict=True))
        rng.shuffle(pairs)
        shuffled = member_readings([v for v, _ in pairs], [w for _, w in pairs])
        after = weighted_median(combine_input(shuffled), {}).statistic
        assert before is not None and after is not None
        assert canonical_decimal(before) == canonical_decimal(after)


def test_weighted_median_of_one_member_is_its_value() -> None:
    readings = member_readings(
        ["7.5", "100"],
        weights=["2", None],
        signals=[{"field:c": 2.0}, {"field:c": None}],
    )
    reduction = weighted_median(combine_input(readings), {})
    assert reduction.statistic is not None
    assert canonical_decimal(reduction.statistic) == "7.5"
    assert reduction.participants == ("member_1",)


def test_weighted_median_golden_fixture_matches() -> None:
    path = FIXTURE_DIR / "weighted_median@1.json"
    fixture = json.loads(path.read_text("utf-8"))
    assert fixture["op"] == "weighted_median@1"
    assert fixture["stage"] == "reduce"
    descriptor = find("weighted_median@1")
    for case in fixture["cases"]:
        assert run_case(descriptor, case) == case["expect"], case["name"]
