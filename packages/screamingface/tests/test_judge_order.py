"""sf.Judge(..., order="min"): the lowest judge score wins (E4b unit 5, JO#1-JO#13).

FEATURE: judge-order — a benchmark author scores answers where a lower number is better.
STORY: as a benchmark author, I want a third-party judge to score each answer where a lower score is
better, and to return the original answer with the lowest score.
INVARIANT: a judge without an order is the same judge as order="max".
INVARIANT: the order is only the select step: a min judge writes the one neutral template (D2).
"""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from _nodes import FusionNode, JudgeNode, ReduceNode, fusion_node, lowered
from url4 import Expression, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.judge import JUDGE_TEMPLATES
from screamingface.reducer import Reducer
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


def _judge(**kw: Any) -> JudgeNode:
    """A scores judge node on provider/j; ``kw`` goes to JudgeNode (order, params, returns...).

    WHY the internal node: the order is a field of the node that a url4 rebuilds; the surface
    spells it as the select step (``sf.Judge(...) >> sf.ArgMin("score:judge")``).
    """
    options: dict[str, Any] = {"returns": "scores", "rubric": RUBRIC, **kw}
    return JudgeNode("provider/j", **options)


def _url4(synthesizer: Reducer, members: list[Any] | None = None, **fusion: Any) -> str:
    recipe = fusion_node(members or members3(), synthesizer, **fusion)
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
    # JO-3: a judge with no order compiles max_score and the neutral template (judge-template@2).
    judge = JudgeNode("provider/j", returns="scores", rubric=RUBRIC)

    assert combine_spec_text(judge, member_count=3, operators=flow_operators()) == _MAX_SPEC
    prompt = _judge_prompt(_url4(judge))
    assert prompt == JUDGE_TEMPLATES["scores"] + RUBRIC
    assert prompt.split("\n", 1)[0] == "judge-template@2 returns=scores"
    assert "Score each member as the rubric says." in prompt


def test_sdk_judge_order_min_compiles_best_holder_min() -> None:
    # JO-1: order="min" selects the lowest score with best_holder@1 {"order":"min"}.
    assert (
        combine_spec_text(_judge(order="min"), member_count=3, operators=flow_operators())
        == _MIN_SPEC
    )


def test_sdk_judge_order_min_writes_the_neutral_template() -> None:
    # JO-2 / D2: the judge call of a min judge is the max judge's call; the rubric gives the
    # direction, and the order is only the select step.
    prompt = _judge_prompt(_url4(_judge(order="min")))

    assert prompt == JUDGE_TEMPLATES["scores"] + RUBRIC
    assert _judge(order="min")._signal_call().prompt == _judge()._signal_call().prompt


def test_sdk_judge_label_refuses_an_order() -> None:
    # JO-E1: a label names one member, so it has no order.
    with pytest.raises(ValueError, match=r"Judge order='min' needs returns='scores'"):
        JudgeNode("provider/j", returns="label", rubric=RUBRIC, order="min")
    with pytest.raises(
        ValueError, match=r"sf\.Reduce\('judge'\): Judge order='min' needs returns='scores'"
    ):
        ReduceNode(
            "judge",
            judge=JudgeNode("provider/j", returns="label", rubric=RUBRIC),
            order="min",
        )
    # control: order="max" on a label is the same judge as no order
    assert JudgeNode("provider/j", returns="label", rubric=RUBRIC, order="max") == JudgeNode(
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
        JudgeNode(
            "provider/j",
            returns="scores",
            rubric=RUBRIC,
            order=order,  # type: ignore[arg-type]
        )
    with pytest.raises(
        ValueError, match=r"sf\.Reduce\('judge'\) option 'order' must be 'max' or 'min'"
    ):
        ReduceNode("judge", judge=_judge(), order=order)


def test_url4_round_trip_rebuilds_an_order_min_judge_and_judge_block() -> None:
    # JO-D2 (H x M): the url4 keeps the order; the SDK rebuilds it, and the judge block keeps it.
    low = _judge(order="min", params={"temperature": 0})
    url4 = _url4(low)
    source = sf.Url4(url4).to_python()

    assert source.splitlines()[-3:] == [
        "    >> sf.Judge('provider/j', rubric='Pick the most correct answer.', "
        "params={'temperature': 0})",
        "    >> sf.ArgMin('score:judge')",
        ")",
    ]

    rebuilt = lowered(_recovered(url4))
    assert isinstance(rebuilt, FusionNode)
    assert rebuilt.synthesizer == low
    assert rebuilt.synthesizer.order == "min"  # type: ignore[attr-defined]
    assert isinstance(rebuilt.synthesizer, JudgeNode)
    assert _url4(rebuilt.synthesizer) == url4

    block = ReduceNode("judge", judge=_judge(params={"temperature": 0}), order="min")
    assert dict(block.options) == {"judge": low}
    assert _url4(block) == url4

    # the block's rubric override keeps the order; the block's order override replaces it
    assert ReduceNode("judge", judge=low, rubric=_OTHER_RUBRIC).options["judge"].order == "min"  # type: ignore[attr-defined]
    assert ReduceNode("judge", judge=low, order="max").options["judge"] == _judge(
        params={"temperature": 0}
    )


def test_panel_judge_order_min_first_line() -> None:
    # JO-D4 (M x L): the panel form has the input tail and no order tail.
    low = _judge(order="min")
    members = ["provider/a", "provider/b", sf.Model("provider/c", optional=True)]
    url4 = _url4(low, members, quorum=2)
    prompt = _judge_prompt(url4)

    assert prompt.split("\n", 1)[0] == "judge-template@2 returns=scores input=panel"
    assert '"panel" is the JSON text of a list' in prompt
    assert "Score each member as the rubric says." in prompt
    assert sf.Url4(url4).to_python().splitlines()[-3:] == [
        f"    >> sf.Judge('provider/j', rubric={RUBRIC!r})",
        "    >> sf.ArgMin('score:judge')",
        ")",
    ]
    assert _url4(lowered(_recovered(url4)).synthesizer, members, quorum=2) == url4


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
    assert eval(repr(low), {"Judge": JudgeNode}) == low  # noqa: S307 - our own repr
    assert low != plain
    assert explicit == plain
    assert hash(explicit) == hash(plain)
    assert len({low, plain, explicit}) == 2
    assert plain.order == "max"  # type: ignore[attr-defined]
    assert low.order == "min"  # type: ignore[attr-defined]
    assert _url4(explicit) == _url4(plain)
