"""mean@1 and weighted_mean@1: an exact, deterministic mean of the members' numbers (E4b unit 3).

FEATURE: a Fusion returns the mean or the weighted mean of its members' numbers, or the member
nearest the mean, without a model synthesizer (mean PRD, S3 and S4).
STORY: as a benchmark author, I average answers with static or confidence weights, and a member
with no usable weight takes no part in the result.
INVARIANT defended: the sums are exact in DECIMAL_CONTEXT and only the one division is rounded to
34 significant digits (P1); a member dropped for its weight is never the nearest member (P9).
"""

from __future__ import annotations

import random
from decimal import ROUND_DOWN, Context, Decimal, localcontext
from typing import Any

import pytest
from combine_fields_support import step
from combine_golden_support import (
    builtin_median_spec,
    find,
    load_fixtures,
    member_readings,
    reduce_result,
    run_case,
    select_result,
)
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import CombineOutcome
from screamingface_engine.combine.ports import NoVotes, Reduction, SpecInvalid, canonical_decimal

_ANSWER = step("json_field@1", path="answer")
_CONFIDENCE = {"signal": "field:confidence"}


def _mean_spec(
    member_count: int,
    *,
    reduce: str = "mean@1",
    select: str = "value@1",
    extract: dict[str, Any] | None = None,
    weights: object = None,
) -> dict[str, Any]:
    return vote_spec(
        member_count,
        reducer="mean",
        extract=step("last_number@1") if extract is None else extract,
        normalize=step("numeric@1"),
        reduce=step(reduce),
        select=step(select),
        weights=weights,
    )


def _run(spec: dict[str, Any], texts: list[str]) -> CombineOutcome:
    return run(spec_text(spec), context_text(texts), registry=BUILTIN_OPERATORS)


def _confidence(values: list[float | None]) -> list[dict[str, float | None]]:
    return [{"field:confidence": value} for value in values]


def test_mean_rounds_a_repeating_division_to_34_significant_digits() -> None:
    # WHY: 4/3 must not carry 1000 digits; the division is one rounding at 34 digits (E4b P1).
    assert (
        canonical_decimal(reduce_result("mean@1", member_readings(["1", "1", "2"])).statistic)
        == "1.333333333333333333333333333333333"
    )
    assert (
        _run(_mean_spec(3), ["x = 1", "x = 1", "x = 2"]).output
        == "1.333333333333333333333333333333333"
    )


def test_weighted_mean_drops_a_member_with_no_usable_weight() -> None:
    # INVARIANT: a member with a missing, zero, negative or non-number weight is not in the sum.
    spec = _mean_spec(6, reduce="weighted_mean@1", extract=_ANSWER, weights=_CONFIDENCE)
    texts = [
        '{"answer":10,"confidence":1}',
        '{"answer":20,"confidence":0}',
        '{"answer":30,"confidence":-2}',
        '{"answer":40}',
        '{"answer":50,"confidence":"high"}',
        '{"answer":60,"confidence":3}',
    ]
    outcome = _run(spec, texts)
    assert outcome.output == "47.5"
    assert [m.weight for m in outcome.evidence.members] == [1.0, None, None, None, None, 3.0]
    assert [m.signals["field:confidence"] for m in outcome.evidence.members] == [
        1.0,
        0.0,
        -2.0,
        None,
        None,
        3.0,
    ]
    assert outcome.evidence.result.status == "answered"


def test_nearest_after_weighted_mean_never_picks_a_dropped_member() -> None:
    # INVARIANT (P9): member_3 holds the mean (17.5) but has weight 0, so it is not a candidate.
    readings = member_readings(["10", "40", "17.5"])
    selection = select_result(
        "nearest@1",
        Reduction(statistic=Decimal("17.5"), participants=("member_1", "member_2")),
        readings,
    )
    assert selection.chosen == ("member_1",)
    assert selection.tie is False
    assert selection.agreement == 0.5

    spec = _mean_spec(
        3, reduce="weighted_mean@1", select="nearest@1", extract=_ANSWER, weights=_CONFIDENCE
    )
    texts = [
        '{"answer":10,"confidence":3}',
        '{"answer":40,"confidence":1}',
        '{"answer":17.5,"confidence":0}',
    ]
    outcome = _run(spec, texts)
    assert outcome.output == texts[0]
    assert outcome.evidence.chosen == ["member_1"]
    assert outcome.evidence.mean == "17.5"
    assert outcome.evidence.tie is False
    assert outcome.evidence.agreement == 0.5


def test_weighted_mean_with_no_usable_member_raises_no_votes() -> None:
    readings = member_readings(["10", "20"], weights=[None, None], signals=_confidence([None, 0.0]))
    with pytest.raises(NoVotes) as caught:
        reduce_result("weighted_mean@1", readings)
    assert caught.value.reason == "no_votes"

    spec = _mean_spec(2, reduce="weighted_mean@1", extract=_ANSWER, weights=_CONFIDENCE)
    outcome = _run(spec, ['{"answer":10,"confidence":0}', '{"answer":20}'])
    assert outcome.output == ""
    assert outcome.evidence.result.status == "abstain"
    assert outcome.evidence.result.reason == "no_votes"
    assert outcome.evidence.mean is None
    assert outcome.evidence.chosen == []


def test_mean_returns_the_plain_average_as_statistic() -> None:
    assert reduce_result("mean@1", member_readings(["10", "20", "60"])).statistic == Decimal(30)
    assert _run(_mean_spec(3), ["x = 10", "x = 20", "x = 60"]).output == "30"


def test_weighted_mean_returns_sum_wx_over_sum_w() -> None:
    reduction = reduce_result(
        "weighted_mean@1", member_readings(["10", "20", "60"], weights=["1", "1", "2"])
    )
    assert reduction.statistic == Decimal("37.5")
    assert reduction.participants == ("member_1", "member_2", "member_3")


def test_weighted_mean_without_spec_weights_is_spec_invalid_and_mean_ignores_weights() -> None:
    # P2 and CS-I1: weighted_mean@1 needs spec weights; mean@1 never reads them.
    with pytest.raises(SpecInvalid, match="weighted_mean@1 needs weights") as caught:
        _run(_mean_spec(3, reduce="weighted_mean@1"), ["x = 10", "x = 20", "x = 60"])
    assert caught.value.code == "combine_spec_invalid"

    weights = {"member_1": 1.0, "member_2": 1.0, "member_3": 100.0}
    assert _run(_mean_spec(3, weights=weights), ["x = 10", "x = 20", "x = 60"]).output == "30"


def test_mean_skips_failed_and_valueless_members() -> None:
    assert reduce_result("mean@1", member_readings(["10", None, "20"])).statistic == Decimal(15)

    outcome = _run(_mean_spec(3), ["x = 10", "no number here", "x = 20"])
    assert outcome.output == "15"
    assert outcome.evidence.members[1].status == "fail"
    assert outcome.evidence.dropped == 1


def test_mean_golden_fixtures_match() -> None:
    fixtures = load_fixtures()
    for op_id in ("mean@1", "weighted_mean@1"):
        for case in fixtures[op_id]["cases"]:
            assert run_case(find(op_id), case) == case["expect"], case["name"]


def test_nearest_with_no_participants_is_unchanged_for_median() -> None:
    readings = member_readings(["3", "9", "9", "12"])
    selection = select_result("nearest@1", reduce_result("median@1", readings), readings)
    assert selection.chosen == ("member_2",)
    assert selection.tie is False
    assert selection.agreement == 0.5


def test_nearest_after_mean_returns_the_closest_member_text() -> None:
    outcome = _run(_mean_spec(3, select="nearest@1"), ["x = 10", "x = 20", "x = 60"])
    assert outcome.output == "x = 20"
    assert outcome.evidence.chosen == ["member_2"]
    assert outcome.evidence.tie is False


def test_nearest_tie_after_mean_goes_to_the_first_member() -> None:
    outcome = _run(_mean_spec(2, select="nearest@1"), ["x = 10", "x = 30"])
    assert outcome.output == "x = 10"
    assert outcome.evidence.tie is True
    assert outcome.evidence.agreement == 0.5


def test_float_weight_becomes_its_str_decimal() -> None:
    # WHY: a float path would give 16.666666666666664 (E4b MN-D5).
    outcome = _run(
        _mean_spec(2, reduce="weighted_mean@1", weights={"member_1": 0.1, "member_2": 0.2}),
        ["x = 10", "x = 20"],
    )
    assert outcome.output == "16.66666666666666666666666666666667"
    assert [m.weight for m in outcome.evidence.members] == [0.1, 0.2]


def test_mean_of_one_usable_member_is_its_value() -> None:
    assert (
        canonical_decimal(reduce_result("mean@1", member_readings(["7.25", None])).statistic)
        == "7.25"
    )
    reduction = reduce_result(
        "weighted_mean@1",
        member_readings(["7.25", "100"], weights=["2", None], signals=_confidence([2.0, None])),
    )
    assert canonical_decimal(reduction.statistic) == "7.25"
    assert reduction.participants == ("member_1",)


def test_mean_sum_is_exact_for_negative_and_long_values() -> None:
    # WHY: a 34-digit sum would lose `tiny` when it adds `big` (E4b MN-D7).
    big = "123456789012345678901234567890123456789012345678.12345678901234"
    tiny = "0.00000000000001"
    neg = "-123456789012345678901234567890123456789012345678.12345678901234"
    assert (
        canonical_decimal(reduce_result("mean@1", member_readings([big, tiny, neg])).statistic)
        == "0." + "0" * 14 + "3" * 34
    )
    # INVARIANT: 0.1 + 0.2 - 0.3 is exactly 0 (a float gives 5.55E-17).
    assert (
        canonical_decimal(
            reduce_result("mean@1", member_readings(["0.1", "0.2", "-0.3"])).statistic
        )
        == "0"
    )


def test_evidence_for_mean_sets_mean_and_leaves_median_null() -> None:
    outcome = _run(_mean_spec(3), ["x = 10", "x = 20", "x = 60"])
    evidence = outcome.evidence
    assert evidence.reducer == "mean"
    assert evidence.mean == "30"
    assert evidence.median is None
    assert [m.value for m in evidence.members] == ["10", "20", "60"]
    assert [m.weight for m in evidence.members] == [None, None, None]
    assert evidence.operators == ["last_number@1", "numeric@1", "mean@1", "value@1"]
    keys = list(evidence.model_dump(by_alias=True))
    assert keys[keys.index("median") + 1] == "mean"

    # P8: a median keeps its v1 bytes, so it writes no `mean` key.
    median = _run(builtin_median_spec(3, "value@1"), ["x = 10", "x = 20", "x = 60"]).evidence
    assert "mean" not in median.model_dump(by_alias=True)
    assert median.median == "20"


@pytest.mark.parametrize("seed", range(20))
def test_mean_is_byte_identical_on_replay(seed: int) -> None:
    # INVARIANT: same spec and context give the same bytes, even when the global context changes.
    rng = random.Random(1289 + seed)
    n = rng.randint(1, 8)
    texts = [f"x = {rng.randint(-(10**6), 10**6)}.{rng.randint(0, 999):03d}" for _ in range(n)]
    weights = {f"member_{i}": rng.choice([0.1, 0.25, 1.0, 3.0, 7.5]) for i in range(1, n + 1)}
    spec = _mean_spec(
        n,
        reduce="weighted_mean@1",
        select=rng.choice(["value@1", "nearest@1"]),
        weights=weights,
    )
    first = _run(spec, texts)
    with localcontext(Context(prec=3, rounding=ROUND_DOWN)):
        second = _run(spec, texts)
    assert (first.output, first.evidence.model_dump_json(by_alias=True)) == (
        second.output,
        second.evidence.model_dump_json(by_alias=True),
    )


@pytest.mark.parametrize("seed", range(20))
def test_mean_of_equal_weights_equals_plain_mean(seed: int) -> None:
    # Oracle: w * S / (n * w) = S / n exactly, so one correctly rounded division gives the same.
    rng = random.Random(4242 + seed)
    n = rng.randint(1, 12)
    values = [
        canonical_decimal(Decimal(rng.randint(-(10**9), 10**9)).scaleb(-rng.randint(0, 6)))
        for _ in range(n)
    ]
    w = rng.choice(["0.5", "1", "3", "7.25"])
    plain = reduce_result("mean@1", member_readings(values)).statistic
    weighted = reduce_result("weighted_mean@1", member_readings(values, weights=[w] * n)).statistic
    assert plain is not None
    assert weighted is not None
    assert canonical_decimal(weighted) == canonical_decimal(plain)
