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
    with pytest.raises(ValueError, match=r"^sf\.ArgMax output='a\.b' must be a top-level field"):
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


def test_first_compares_a_number_as_its_json_text() -> None:
    assert (sx.field("score") == 7) == (sx.field("score") == "7")
    assert sx.First(where=sx.field("score") == 7) == sx.First(where=sx.field("score") == "7")
    assert _synthesizer(sx.First(where=sx.field("score") == 7)) == sf.Pick("score", equals="7")


def test_first_refuses_a_bool_with_the_numeric_normalizer() -> None:
    with pytest.raises(
        ValueError,
        match=r"^sf\.field == True or False cannot be compared with normalize='numeric'$",
    ):
        _ = sx.field("ok", normalize="numeric") == True  # noqa: E712


@pytest.mark.parametrize(
    ("value", "error", "message"),
    [
        (None, TypeError, r"^sf\.field compares with a string, a number or a bool, not None$"),
        ([1], TypeError, r"^sf\.field compares with a string, a number or a bool, not \[1\]$"),
        (" ", ValueError, r"^sf\.field == ' ' must not be blank$"),
        (float("nan"), ValueError, r"^sf\.field == nan must be finite$"),
    ],
    ids=["none", "list", "blank", "nan"],
)
def test_field_equals_checks_its_value_with_field_messages(
    value: object, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        _ = sx.field("x") == value


@pytest.mark.parametrize("step", [sx.ArgMax, sx.ArgMin])
def test_output_has_the_step_message(step: type[sx.ArgMax]) -> None:
    name = step.__name__
    with pytest.raises(
        ValueError,
        match=rf"^sf\.{name} output='' must be a top-level field name like 'answer' \(a letter "
        r"or _, then letters, digits or _; at most 64 characters\)$",
    ):
        step("cost_usd", output="")
    with pytest.raises(TypeError, match=rf"^sf\.{name} output= must be a string$"):
        step("cost_usd", output=3)  # type: ignore[arg-type]


def test_first_output_has_the_first_message() -> None:
    with pytest.raises(ValueError, match=r"^sf\.First output='a\.b' must be a top-level field"):
        sx.First(where=sx.field("x") == 1, output="a.b")


def test_argmin_is_not_an_argmax() -> None:
    assert not issubclass(sx.ArgMin, sx.ArgMax)
    assert not isinstance(sx.ArgMin("cost_usd"), sx.ArgMax)


def test_merge_equality_follows_the_field_order() -> None:
    first = {"a": sf.FieldRule.max(), "b": sf.FieldRule.majority()}
    second = {"b": sf.FieldRule.majority(), "a": sf.FieldRule.max()}

    assert sx.Merge(first) == sx.Merge(dict(first))
    assert sx.Merge(first) != sx.Merge(second)


def test_field_checks_its_path_and_normalizer() -> None:
    with pytest.raises(ValueError, match="must be a JSON path"):
        sx.field("a..b")
    with pytest.raises(ValueError, match="normalize must be 'text' or 'numeric'"):
        sx.field("a", normalize="set")  # type: ignore[arg-type]


@pytest.mark.parametrize("where", [sx.field("a"), "a", sf.signal("field:a") == 1])
def test_first_where_takes_a_field_equals_condition(where: object) -> None:
    with pytest.raises(TypeError, match=r"^sf\.First where= takes sf\.field\(path\) == value$"):
        sx.First(where=where)  # type: ignore[arg-type]


def test_a_field_condition_tells_a_bool_from_a_number() -> None:
    assert (sx.field("a") == 1) == (sx.field("a") == 1)
    assert (sx.field("a") == 1) != (sx.field("a") == True)  # noqa: E712
    assert hash(sx.field("a") == 1) == hash(sx.field("a") == 1)
    assert sx.First(where=sx.field("a") == 1) != sx.First(where=sx.field("a") == True)  # noqa: E712
