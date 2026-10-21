"""``sf.Judge`` (a score step) and ``sf.JudgePick`` (a reducer) (E4b surface unit 3, §4, §6).

FEATURE: ``Judge(model, *, rubric, params=None)`` scores every member in one call and puts
``score:judge`` on each one; it does not pick. The steps after it read the scores:
``ArgMax``/``ArgMin("score:judge")``, ``Rank(by="score:judge")``, ``Filter(where=...)`` and
``Vote(weights="score:judge")``. ``JudgePick`` asks a judge model to name one member.
INVARIANT: before the swap every judge lowers to today's ``sf.Judge`` and its ``@1`` template;
the neutral ``@2`` template comes with unit 7.
"""

from __future__ import annotations

import pytest
from _combine_flow_fixtures import flow_operators
from _nodes import (
    FilterNode,
    FusionNode,
    JudgeNode,
    RankNode,
    ReduceNode,
    VoteNode,
    frozen_url4,
    fusion_node,
)

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._surface.lowering import lower

_TRIO = ["provider/a", "provider/b", "provider/c"]
_JUDGE = "provider/judge"
_RUBRIC = "Give a higher number to a more correct answer."


def _judge(**options: object) -> sf.Judge:
    return sf.Judge(_JUDGE, rubric=_RUBRIC, **options)  # type: ignore[arg-type]


def _scores(**options: object) -> JudgeNode:
    return JudgeNode(_JUDGE, returns="scores", rubric=_RUBRIC, **options)  # type: ignore[arg-type]


def _synthesizer(chain: sf.Recipe) -> object:
    node = lower(chain)
    assert isinstance(node, FusionNode)
    return node.synthesizer


def test_a_judge_holds_its_model_rubric_and_params() -> None:
    judge = _judge(params={"temperature": 0})

    assert judge.model == _JUDGE
    assert judge.rubric == _RUBRIC
    assert dict(judge.params) == {"temperature": 0}


def test_judge_equality_tells_a_bool_param_from_a_number() -> None:
    assert _judge(params={"temperature": 1}) == _judge(params={"temperature": 1})
    assert _judge(params={"temperature": 1}) != _judge(params={"temperature": True})


@pytest.mark.parametrize(
    ("options", "error", "message"),
    [
        ({"rubric": " "}, ValueError, "judge rubric must not be empty"),
        ({"rubric": 3}, TypeError, "judge rubric must be a string"),
        ({"rubric": "r", "params": {"model": "x"}}, ValueError, "reserved"),
    ],
    ids=["blank-rubric", "rubric-type", "reserved-param"],
)
def test_a_judge_checks_its_options_with_the_rules_of_today(
    options: dict[str, object], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        sf.Judge(_JUDGE, **options)  # type: ignore[arg-type]
    with pytest.raises(error, match=message):
        sf.JudgePick(_JUDGE, **options)  # type: ignore[arg-type]


@pytest.mark.parametrize("step", [_judge(), sf.JudgePick(_JUDGE, rubric="Pick one.")])
def test_a_judge_is_a_step_not_a_member(step: object) -> None:
    with pytest.raises(TypeError, match=r"is a step, not a recipe: put it after a sf\.Fanout$"):
        sf.Fanout(["provider/a", step])  # type: ignore[list-item]


def test_argmax_by_judge_lowers_to_the_scores_judge_of_today() -> None:
    chain = sf.Fanout(_TRIO) >> _judge(params={"temperature": 0}) >> sf.ArgMax("score:judge")

    assert _synthesizer(chain) == _scores(params={"temperature": 0})


def test_argmin_by_judge_lowers_to_the_min_order_judge_of_today() -> None:
    chain = sf.Fanout(_TRIO) >> _judge() >> sf.ArgMin("score:judge")

    assert _synthesizer(chain) == _scores(order="min")


def test_a_judge_weighted_vote_lowers_to_the_paired_vote_of_today() -> None:
    chain = sf.Fanout(_TRIO) >> _judge() >> sf.Vote(over="last_number", weights="score:judge")

    assert _synthesizer(chain) == VoteNode(
        extract="last_number", weights=sf.signal("score:judge"), judge=_scores()
    )


def test_a_judge_weighted_extract_vote_lowers_to_the_weighted_block() -> None:
    extract = sf.Extract("last_number", normalize="numeric")
    chain = sf.Fanout(_TRIO) >> _judge() >> sf.Vote(over=extract, weights="score:judge")

    assert _synthesizer(chain) == ReduceNode(
        "weighted", extract=extract, weights=sf.signal("score:judge"), judge=_scores()
    )


def test_a_judge_rank_lowers_to_the_rank_by_judge_of_today() -> None:
    chain = (
        sf.Fanout(_TRIO)
        >> _judge()
        >> sf.Rank(2, by="score:judge", order="min")
        >> sf.Synthesize("provider/w")
    )

    assert lower(chain) == sf.Pipeline(
        [fusion_node(_TRIO, RankNode(k=2, by=_scores(), order="min")), "provider/w"]
    )


def test_a_judge_filter_lowers_to_the_filter_with_a_judge_of_today() -> None:
    where = sf.signal("score:judge") >= 7
    chain = sf.Fanout(_TRIO) >> _judge() >> sf.Filter(where=where) >> sf.Synthesize("provider/w")

    assert lower(chain) == sf.Pipeline(
        [fusion_node(_TRIO, FilterNode(where=where, judge=_scores())), "provider/w"]
    )


def test_judge_pick_lowers_to_the_label_judge_of_today() -> None:
    chain = sf.Fanout(_TRIO) >> sf.JudgePick(_JUDGE, rubric="Pick one.", params={"seed": 1})

    assert _synthesizer(chain) == JudgeNode(
        _JUDGE, returns="label", rubric="Pick one.", params={"seed": 1}
    )


_JU1 = (
    r"^sf\.{0} does not read a judge's scores as weights; use "
    r"sf\.Vote\(weights='score:judge'\) or sf\.ArgMax\('score:judge'\)$"
)


def test_ju1_median_and_mean_refuse_a_judge_weight_when_they_are_built() -> None:
    # JU-1 is today's rule and it runs when the step is built: in a chain it raises before the
    # >> that would close the block, after the Fanout and the Judge are in the chain.
    scored = sf.Fanout(_TRIO) >> _judge()
    median = _JU1.format("Median")
    with pytest.raises(ValueError, match=median):
        _ = scored >> sf.Median(weights="score:judge")
    mean = _JU1.format("Mean")
    with pytest.raises(ValueError, match=mean):
        sf.Mean(weights="score:judge")


@pytest.mark.parametrize("step", [sf.ArgMax, sf.ArgMin])
def test_ju2_a_judge_pick_takes_no_output(step: type[sf.ArgMax]) -> None:
    with pytest.raises(
        ValueError,
        match=r"^output= reads a member field; a judge pick returns the member text$",
    ):
        step("score:judge", output="answer")


def test_a_judge_block_compiles_to_the_bytes_of_today() -> None:
    chain = sf.Fanout(_TRIO) >> _judge() >> sf.ArgMax("score:judge")

    # today's Fusion of _TRIO with _scores()
    assert compile_candidate(chain, operators=flow_operators()).url4 == frozen_url4(
        "judge_step:scores-judge"
    )


def test_judge_repr_shows_params_only_when_set() -> None:
    assert repr(sf.Judge(_JUDGE, rubric="r")) == "Judge('provider/judge', rubric='r')"
    assert repr(sf.JudgePick(_JUDGE, rubric="r", params={"seed": 1})) == (
        "JudgePick('provider/judge', rubric='r', params={'seed': 1})"
    )
