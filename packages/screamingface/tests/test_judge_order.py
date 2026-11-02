"""sf.Judge(..., order="min"): the lowest judge score wins (E4b unit 5, JO#1-JO#13).

FEATURE: judge-order — a benchmark author scores answers where a lower number is better.
STORY: as a benchmark author, I want a third-party judge to score each answer where a lower score is
better, and to return the original answer with the lowest score.
INVARIANT: a judge without an order (or with order="max") compiles the same bytes as before.
INVARIANT: order="min" is a Fusion synthesizer only; Rank, Vote and Filter refuse it.
"""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from url4 import Expression, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.judge import JUDGE_TEMPLATES
from screamingface.reducer import Reducer, _refuse_min_order_judge
from screamingface.url4 import _calls

_SPEC_HEAD = '{"extract":null,"members":["member_1","member_2","member_3"],"normalize":null,'
_SCORES_REDUCE = '"reduce":{"args":{"source":"judge"},"op":"scores@1"},"reducer":"judge",'
_SCHEMA = '"schema":"screamingface.combine-spec.v1",'
# WHY the literal specs: the judge spec bytes of today (max) and of order="min" (JO-3, JO-1).
_MAX_SPEC = (
    _SPEC_HEAD
    + _SCORES_REDUCE
    + _SCHEMA
    + '"select":{"args":{},"op":"max_score@1"},"weights":null}'
)
_MIN_SPEC = (
    _SPEC_HEAD
    + _SCORES_REDUCE
    + _SCHEMA
    + '"select":{"args":{"order":"min"},"op":"best_holder@1"},"weights":null}'
)
_OTHER_RUBRIC = "Prefer the shortest correct answer."


def _judge(**kw: Any) -> sf.Judge:
    """A scores judge on provider/j; ``kw`` goes to sf.Judge (order, params, returns...)."""
    options: dict[str, Any] = {"returns": "scores", "rubric": RUBRIC, **kw}
    return sf.Judge("provider/j", **options)


def _url4(synthesizer: Reducer, members: list[Any] | None = None, **fusion: Any) -> str:
    recipe = sf.Fusion(members or members3(), synthesizer=synthesizer, **fusion)
    return compile_candidate(recipe, operators=flow_operators()).url4


def _judge_prompt(url4: str) -> str:
    root = build(url4)
    assert isinstance(root, Expression)
    return _calls(root)["judge_1"].prompt


def _recovered(url4: str) -> sf.Recipe:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    candidate = namespace["candidate"]
    assert isinstance(candidate, sf.Recipe)
    return candidate


def test_sdk_judge_scores_without_order_compiles_max_score() -> None:
    # JO-3 (CHAR): a judge with no order keeps today's bytes and today's template.
    judge = sf.Judge("provider/j", returns="scores", rubric=RUBRIC)

    assert combine_spec_text(judge, member_count=3, operators=flow_operators()) == _MAX_SPEC
    prompt = _judge_prompt(_url4(judge))
    assert prompt == JUDGE_TEMPLATES["scores"] + RUBRIC
    assert prompt.split("\n", 1)[0] == "judge-template@1 returns=scores"
    assert "A higher number means a better answer." in prompt


def test_sdk_judge_order_min_compiles_best_holder_min() -> None:
    # JO-1: order="min" selects the lowest score with best_holder@1 {"order":"min"}.
    assert (
        combine_spec_text(_judge(order="min"), member_count=3, operators=flow_operators())
        == _MIN_SPEC
    )


def test_sdk_judge_order_min_tells_the_judge_lower_is_better() -> None:
    # JO-2 / ans:Q11: the judge is told that a lower number is better.
    prompt = _judge_prompt(_url4(_judge(order="min")))
    expected = (
        JUDGE_TEMPLATES["scores"]
        .replace(
            "judge-template@1 returns=scores\n",
            "judge-template@1 returns=scores order=min\n",
            1,
        )
        .replace(
            "A higher number means a better answer.", "A lower number means a better answer.", 1
        )
        + RUBRIC
    )

    assert prompt.split("\n", 1)[0] == "judge-template@1 returns=scores order=min"
    assert "A lower number means a better answer." in prompt
    assert "A higher number" not in prompt
    assert prompt == expected
    assert _judge(order="min")._signal_call().prompt == expected


def test_sdk_judge_label_refuses_an_order() -> None:
    # JO-E1: a label names one member, so it has no order.
    with pytest.raises(ValueError, match=r"Judge order='min' needs returns='scores'"):
        sf.Judge("provider/j", returns="label", rubric=RUBRIC, order="min")
    with pytest.raises(
        ValueError, match=r"sf\.Reduce\('judge'\): Judge order='min' needs returns='scores'"
    ):
        sf.Reduce(
            "judge",
            judge=sf.Judge("provider/j", returns="label", rubric=RUBRIC),
            order="min",
        )
    # control: order="max" on a label is the same judge as no order
    assert sf.Judge("provider/j", returns="label", rubric=RUBRIC, order="max") == sf.Judge(
        "provider/j", returns="label", rubric=RUBRIC
    )


@pytest.mark.parametrize(
    "order",
    ["lowest", "MIN", "", None, 1],
    ids=["lowest", "upper", "empty", "none", "int"],
)
def test_sdk_judge_refuses_an_unknown_order(order: object) -> None:
    # JO-E2: only "max" and "min" are orders. The block form checks the same way (blocks.py).
    with pytest.raises(ValueError, match="Judge order must be 'max' or 'min', not "):
        sf.Judge(
            "provider/j",
            returns="scores",
            rubric=RUBRIC,
            order=order,  # type: ignore[arg-type]
        )
    with pytest.raises(
        ValueError, match=r"sf\.Reduce\('judge'\) option 'order' must be 'max' or 'min'"
    ):
        sf.Reduce("judge", judge=_judge(), order=order)


def test_rank_vote_and_filter_refuse_a_min_order_judge() -> None:
    # JO-D1 (H x M): Rank, Vote and Filter have their own order or threshold, so a min judge is
    # refused there. The messages never echo the rubric.
    low = _judge(order="min")
    high = _judge()

    with pytest.raises(ValueError) as caught:
        sf.Rank(2, by=low)
    assert str(caught.value).startswith("Rank cannot use sf.Judge(..., order='min')")

    with pytest.raises(ValueError) as caught:
        sf.Reduce("top_k", k=2, by=low)
    assert str(caught.value).startswith(
        "sf.Reduce('top_k'): Rank cannot use sf.Judge(..., order='min')"
    )
    assert RUBRIC not in str(caught.value)

    with pytest.raises(ValueError) as caught:
        sf.Vote(
            extract="last_number",
            normalize="numeric",
            weights=sf.signal("score:judge"),
            judge=low,
        )
    assert str(caught.value).startswith("Vote cannot use sf.Judge(..., order='min')")
    assert RUBRIC not in str(caught.value)

    with pytest.raises(ValueError) as caught:
        sf.Reduce(
            "weighted",
            extract=sf.Extract("last_number", normalize="numeric"),
            weights=sf.signal("score:judge"),
            judge=low,
        )
    assert str(caught.value).startswith(
        "sf.Reduce('weighted') cannot use sf.Judge(..., order='min')"
    )
    assert RUBRIC not in str(caught.value)

    # Filter half: unit 6 wires sf.Filter(judge=); here only the shared check is pinned.
    with pytest.raises(ValueError) as caught:
        _refuse_min_order_judge(low, "Filter")
    assert str(caught.value).startswith("Filter cannot use sf.Judge(..., order='min')")
    assert RUBRIC not in str(caught.value)

    # controls: a judge with the default order passes every check
    sf.Rank(2, by=high)
    sf.Vote(
        extract="last_number",
        normalize="numeric",
        weights=sf.signal("score:judge"),
        judge=high,
    )
    _refuse_min_order_judge(high, "Filter")


def test_url4_round_trip_rebuilds_an_order_min_judge_and_judge_block() -> None:
    # JO-D2 (H x M): the url4 keeps the order; the SDK rebuilds it, and the judge block keeps it.
    low = _judge(order="min", params={"temperature": 0})
    url4 = _url4(low)
    source = sf.Url4(url4).to_python()

    assert (
        "synthesizer=sf.Judge('provider/j', returns='scores', "
        "rubric='Pick the most correct answer.', params={'temperature': 0}, order='min')" in source
    )

    rebuilt = _recovered(url4)
    assert isinstance(rebuilt, sf.Fusion)
    assert rebuilt.synthesizer == low
    assert rebuilt.synthesizer.order == "min"  # type: ignore[attr-defined]
    assert isinstance(rebuilt.synthesizer, sf.Judge)
    assert _url4(rebuilt.synthesizer) == url4

    block = sf.Reduce("judge", judge=_judge(params={"temperature": 0}), order="min")
    assert dict(block.options) == {"judge": low}
    assert _url4(block) == url4

    # the block's rubric override keeps the order; the block's order override replaces it
    assert sf.Reduce("judge", judge=low, rubric=_OTHER_RUBRIC).options["judge"].order == "min"  # type: ignore[attr-defined]
    assert sf.Reduce("judge", judge=low, order="max").options["judge"] == _judge(
        params={"temperature": 0}
    )

    # tampered template: the order tail is gone, so the url4 is refused
    old = "returns=scores order=min"
    assert old in url4
    with pytest.raises(ValueError, match="unsupported judge call"):
        sf.Url4(url4.replace(old, "returns=scores", 1)).to_python()

    # tampered spec: the select step is the max step, so the url4 is refused
    old_select = '"select":{"args":{"order":"min"},"op":"best_holder@1"}'
    assert old_select in url4
    with pytest.raises(ValueError, match="unsupported judge call"):
        sf.Url4(url4.replace(old_select, '"select":{"args":{},"op":"max_score@1"}', 1)).to_python()


def test_panel_judge_order_min_first_line() -> None:
    # JO-D4 (M x L): the panel form puts the input tail before the order tail.
    low = _judge(order="min")
    members = ["provider/a", "provider/b", sf.Model("provider/c", optional=True)]
    url4 = _url4(low, members, quorum=2)
    prompt = _judge_prompt(url4)

    assert prompt.split("\n", 1)[0] == "judge-template@1 returns=scores input=panel order=min"
    assert '"panel" is the JSON text of a list' in prompt
    assert "A lower number means a better answer." in prompt
    assert (
        f"sf.Judge('provider/j', returns='scores', rubric={RUBRIC!r}, order='min')"
        in sf.Url4(url4).to_python()
    )
    assert _url4(_recovered(url4).synthesizer, members, quorum=2) == url4  # type: ignore[attr-defined]


def test_judge_key_and_repr_include_order() -> None:
    # JO-3 / JO-1: the key and the repr carry the order; the default order keeps the old repr.
    low = _judge(order="min")
    plain = _judge()
    explicit = _judge(order="max")

    assert (
        repr(low) == "Judge('provider/j', returns='scores', "
        "rubric='Pick the most correct answer.', order='min')"
    )
    assert (
        repr(explicit)
        == repr(plain)
        == "Judge('provider/j', returns='scores', rubric='Pick the most correct answer.')"
    )
    assert (
        repr(_judge(order="min", params={"temperature": 0}))
        == "Judge('provider/j', returns='scores', rubric='Pick the most correct answer.', "
        "params={'temperature': 0}, order='min')"
    )
    assert eval(repr(low), {"Judge": sf.Judge}) == low  # noqa: S307 - our own repr
    assert low != plain
    assert explicit == plain
    assert hash(explicit) == hash(plain)
    assert len({low, plain, explicit}) == 2
    assert plain.order == "max"  # type: ignore[attr-defined]
    assert low.order == "min"  # type: ignore[attr-defined]
    assert _url4(explicit) == _url4(plain)


def test_public_surface_lists_judge_order() -> None:
    # JO#13: the approved snapshot edit. The Judge gains the field and the keyword.
    from test_public_surface import build_public_surface

    judge = build_public_surface()["screamingface"]["exports"]["Judge"]
    assert judge["members"].get("order") == "field"
    assert (
        judge["members"]["__init__"]
        == "method (self, model: 'str', *, returns: 'JudgeReturns', rubric: 'str', "
        "params: 'Mapping[str, str | int | float | bool] | None' = None, "
        "order: \"Literal['max', 'min']\" = 'max') -> 'None'"
    )
