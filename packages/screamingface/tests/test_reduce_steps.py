"""The reduce steps ``ArgMax``, ``ArgMin``, ``First``, ``Merge`` and ``JudgePick`` (unit 3, §6).

FEATURE: ``ArgMax``/``ArgMin(by, *, output=None)`` copy the member with the highest or lowest
signal; ``First(*, where=sf.field(path) == value, output=None)`` copies the first member, in
author order, whose JSON field equals the value; ``Merge(fields)`` builds one JSON object.
Each lowers to today's class (AR-1). ``sf.field`` compares with ``==`` only (SI-2), with today's
``Pick(equals=)`` rules.
"""

from __future__ import annotations

import pytest

import screamingface as sf
from screamingface import _surface as sx
from screamingface._surface.lowering import lower

_TRIO = ["provider/a", "provider/b", "provider/c"]


def _synthesizer(step: object) -> object:
    node = lower(sx.Fanout(_TRIO) >> step)  # type: ignore[operator]
    assert isinstance(node, sf.Fusion)
    return node.synthesizer


# ---------------------------------------------------------------- AR-1


def test_ar1_argmax_and_argmin_lower_to_the_pick_by_signal() -> None:
    assert _synthesizer(sx.ArgMax("cost_usd", output="answer")) == sf.Pick(
        by_signal=sf.signal("cost_usd"), order="max", output="answer"
    )
    assert _synthesizer(sx.ArgMin(sf.signal("cost_usd"))) == sf.Pick(
        by_signal=sf.signal("cost_usd"), order="min"
    )


def test_ar1_argmax_and_argmin_are_different_steps() -> None:
    assert sx.ArgMax("cost_usd") != sx.ArgMin("cost_usd")
    assert sx.ArgMax("cost_usd") == sx.ArgMax(sf.signal("cost_usd"))


def test_ar1_first_lowers_to_the_pick_by_field_equals() -> None:
    where = sx.field("answer", normalize="text") == "yes"

    assert _synthesizer(sx.First(where=where, output="answer")) == sf.Pick(
        "answer", equals="yes", normalize="text", output="answer"
    )


def test_ar1_judge_pick_and_merge_lower_to_today() -> None:
    fields = {"answer": sf.FieldRule.majority(normalize="text"), "score": sf.FieldRule.max()}

    assert _synthesizer(sx.Merge(fields)) == sf.Merge(fields=fields)
    assert _synthesizer(sx.JudgePick("provider/j", rubric="Pick one.")) == sf.Judge(
        "provider/j", returns="label", rubric="Pick one."
    )


def test_argmax_by_must_be_one_signal() -> None:
    with pytest.raises(
        TypeError,
        match=r"^sf\.ArgMax by= must be one signal: a key string such as 'cost_usd' or "
        r"sf\.signal\(key\)$",
    ):
        sx.ArgMax(3)  # type: ignore[arg-type]


def test_argmax_output_has_the_rule_of_today() -> None:
    with pytest.raises(ValueError, match="must be a top-level field name"):
        sx.ArgMax("cost_usd", output="a.b")


def test_merge_checks_its_fields_with_the_rules_of_today() -> None:
    with pytest.raises(ValueError, match="Merge needs at least one field"):
        sx.Merge({})


# ---------------------------------------------------------------- SI-2 and the equals rules


@pytest.mark.parametrize(
    "compare",
    [
        lambda f: f > 1,
        lambda f: f >= 1,
        lambda f: f < 1,
        lambda f: f <= 1,
        lambda f: f != 1,
    ],
    ids=["gt", "ge", "lt", "le", "ne"],
)
def test_si2_field_compares_with_equals_only(compare: object) -> None:
    with pytest.raises(
        TypeError,
        match=r"^sf\.field compares with == only; use sf\.signal\('field:\.\.\.'\) for numbers$",
    ):
        compare(sx.field("answer"))  # type: ignore[operator]


def test_first_keeps_the_equals_rule_of_today_a_number_is_json_text() -> None:
    assert _synthesizer(sx.First(where=sx.field("score") == 7)) == sf.Pick("score", equals=7)


def test_first_refuses_a_bool_with_the_numeric_normalizer() -> None:
    with pytest.raises(ValueError, match="cannot be compared with normalize='numeric'"):
        sx.First(where=sx.field("ok", normalize="numeric") == True)  # noqa: E712


def test_field_checks_its_path_and_normalizer() -> None:
    with pytest.raises(ValueError, match="must be a JSON path"):
        sx.field("a..b")
    with pytest.raises(ValueError, match="normalize must be 'text' or 'numeric'"):
        sx.field("a", normalize="set")  # type: ignore[arg-type]


@pytest.mark.parametrize("where", [sx.field("a"), "a", sf.signal("field:a") == 1])
def test_first_where_takes_a_field_equals_condition(where: object) -> None:
    with pytest.raises(TypeError, match=r"^sf\.First where= takes sf\.field\(path\) == value$"):
        sx.First(where=where)  # type: ignore[arg-type]
