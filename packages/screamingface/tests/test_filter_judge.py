"""sf.Filter(judge=...): judge pairing, refusals and url4 round trip (E4b unit 6, FJ#2-5, FJ#11).

FEATURE: ``sf.Filter(where=sf.signal("score:judge") >= 7, judge=sf.Judge(..., returns="scores"))``
keeps the members that a judge scores at or over the threshold. One judge call scores the panel.
STORY: as a benchmark author, a weak draft never reaches the writer, and a bad pairing fails when
the Filter is built, before any model call is paid.
INVARIANT defended: a ``score:judge`` comparison and a scores judge go together, a label judge or an
``order="min"`` judge never reaches a Filter, a url4 rebuilds as the same ``sf.Filter``, and the
judge rubric never appears in an error message.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from _combine_flow_fixtures import flow_operators, members3
from _nodes import FilterNode, FusionNode, JudgeNode, ReduceNode, fusion_node, lowered
from url4 import Expression, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.reducer import Reducer
from screamingface.url4 import _calls

RUBRIC = "Score each draft."
SECRET = "SECRET-RUBRIC-TEXT"
J = sf.Judge("provider/j", rubric=RUBRIC)
JUDGED = sf.signal("score:judge") >= 7
# group F (7f): the old renderer (_python) writes ``sf.<today's class>``; these rows read it with
# the node classes, so they keep working after the swap until 7f deletes them.
_NODES_AS_SF = SimpleNamespace(
    Filter=FilterNode, Judge=JudgeNode, Reduce=ReduceNode, signal=sf.signal, matches=sf.matches
)


def _filter_by_judge() -> FilterNode:
    # WHY a function: the Filter is built inside each test, so a refusal fails that test and not
    # the whole module at import. WHY the node: it is the value that the judge filter chain lowers
    # to, and the url4 rebuild gives it back until the swap (7e).
    return FilterNode(where=JUDGED, judge=JudgeNode("provider/j", returns="scores", rubric=RUBRIC))


def _judge_filter(
    members: Sequence[str | sf.Recipe], quorum: int | Literal["all"] = "all"
) -> sf.Recipe:
    """Fanout >> Judge >> Filter(score:judge) >> Synthesize: the judge filter and its writer."""

    return (
        sf.Fanout(members, quorum=quorum)
        >> J
        >> sf.Filter(where=JUDGED)
        >> sf.Synthesize("provider/next")
    )


def _wrapped(reducer: Reducer) -> sf.Pipeline:
    return sf.Pipeline([fusion_node(members3(), reducer), "provider/next"])


def _url4(reducer: Reducer) -> str:
    return compile_candidate(_wrapped(reducer), operators=flow_operators()).url4


def _recovered(url4: str) -> sf.Recipe:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    candidate = namespace["candidate"]
    assert isinstance(candidate, sf.Recipe)
    return candidate


# --- FJ#2: the compile adds one judge call and the signal ---------------------------------------


def test_sdk_filter_with_judge_compiles_the_judge_call_and_signal() -> None:
    url4 = compile_candidate(_judge_filter(members3()), operators=flow_operators()).url4
    root = build(url4)
    assert isinstance(root, Expression)
    calls = _calls(root)
    outs = "outputs: {member_1: '$model_1', member_2: '$model_2', member_3: '$model_3'}"

    assert "judge_1" in calls
    assert calls["judge_1"].context == "{input: '$input', " + outs + "}"
    assert calls["judge_1"].prompt.splitlines()[0] == "judge-template@2 returns=scores"
    assert calls["judge_1"].prompt.endswith("Rubric:\nScore each draft.")
    assert "Score each member as the rubric says." in calls["judge_1"].prompt
    assert (
        calls["synthesis_1"].context
        == "{input: '$input', " + outs + ", signals: {judge: '$judge_1'}}"
    )
    assert json.loads(calls["synthesis_1"].raw_intent) == {
        "schema": "screamingface.combine-spec.v1",
        "reducer": "filter",
        "members": ["member_1", "member_2", "member_3"],
        "extract": None,
        "normalize": None,
        "reduce": {"op": "filter@1", "args": {"key": "score:judge", "cmp": "ge", "value": 7.0}},
        "select": {"op": "kept@1", "args": {}},
        "weights": None,
    }
    # WHY one judge call for the whole panel: Q10 defers the one-call-per-member form
    assert url4.count("judge-template@2") == 1
    assert '"role":"judge"' in url4


# --- FJ-E3: a score:judge comparison needs a judge ----------------------------------------------


def test_sdk_filter_score_judge_without_judge_is_refused() -> None:
    message = r"^score:judge needs sf\.Judge\(\.\.\.\) after sf\.Fanout$"
    with pytest.raises(ValueError, match=message):
        _ = sf.Fanout(members3()) >> sf.Filter(where=JUDGED) >> sf.Synthesize("provider/next")
    with pytest.raises(ValueError, match=message):
        _ = (
            sf.Fanout(members3())
            >> sf.Filter(where=sf.signal("score:judge") < 3)
            >> sf.Synthesize("provider/next")
        )
    # group F (7f): the filter block form is deleted code (D7-8)
    with pytest.raises(
        ValueError, match=r"^sf\.Reduce\('filter'\): Filter where=.*add judge=sf\.Judge"
    ):
        ReduceNode("filter", where=JUDGED)


# --- FJ-E4: a judge needs a score:judge comparison ----------------------------------------------


def test_sdk_filter_judge_without_score_judge_where_is_refused() -> None:
    secret = sf.Judge("provider/j", rubric=SECRET)
    unread = r"^sf\.Judge scores the members, but no step reads score:judge$"
    for where in (
        sf.signal("field:confidence") >= 0.6,
        sf.matches("yes"),
        sf.signal("cost_usd") <= 0.01,
    ):
        with pytest.raises(ValueError, match=unread) as caught:
            _ = (
                sf.Fanout(members3())
                >> secret
                >> sf.Filter(where=where)
                >> sf.Synthesize("provider/next")
            )
        assert SECRET not in str(caught.value)

    # group F (7f): the rest reads the Filter judge= parameter and the filter block (D7-8)
    old_secret = JudgeNode("provider/j", returns="scores", rubric=SECRET)
    refusal = r"Filter judge is read only by a where=sf\.signal\('score:judge'\) comparison"
    with pytest.raises(ValueError, match=r"^sf\.Reduce\('filter'\): " + refusal) as caught:
        ReduceNode("filter", where=sf.matches("yes"), judge=old_secret)
    assert SECRET not in str(caught.value)

    with pytest.raises(TypeError, match=r"Filter judge must be an sf\.Judge"):
        FilterNode(where=JUDGED, judge="provider/j")  # type: ignore[arg-type]
    with pytest.raises(
        TypeError, match=r"sf\.Reduce\('filter'\) option 'judge' must be an sf\.Judge"
    ):
        ReduceNode("filter", where=JUDGED, judge="provider/j")


# --- FJ-D2: a label judge is refused --------------------------------------------------------------


def test_sdk_filter_refuses_a_label_judge() -> None:
    # group F (7f): it reads only the Filter judge= parameter, which the chain has no place for
    label = JudgeNode("provider/j", returns="label", rubric=SECRET)

    with pytest.raises(
        ValueError, match=r"Filter judge needs sf\.Judge\(\.\.\., returns='scores'\)"
    ) as caught:
        FilterNode(where=JUDGED, judge=label)
    assert SECRET not in str(caught.value)

    with pytest.raises(
        ValueError, match=r"Filter judge needs sf\.Judge\(\.\.\., returns='scores'\)"
    ) as caught:
        ReduceNode("filter", where=JUDGED, judge=label)
    assert SECRET not in str(caught.value)


# --- FJ#11: the url4 round trip rebuilds a judge Filter and the filter block --------------------


@pytest.mark.parametrize("shape", ["plain", "quorum"])
def test_url4_round_trip_rebuilds_a_judge_filter_and_filter_block(shape: str) -> None:
    if shape == "plain":
        chain = _judge_filter(members3())
    else:
        # WHY a quorum panel: the judge reads the panel, and the rebuild must still find its call
        chain = _judge_filter(
            ["provider/a", "provider/b", sf.Model("provider/c", optional=True)], quorum=2
        )
    url4 = compile_candidate(chain, operators=flow_operators()).url4

    assert sf.Url4(url4).to_python().splitlines()[-4:] == [
        "    >> sf.Judge('provider/j', rubric='Score each draft.')",
        "    >> sf.Filter(where=sf.signal('score:judge') >= 7.0)",
        "    >> sf.Synthesize('provider/next')",
        ")",
    ]
    recovered = _recovered(url4)
    assert recovered == chain
    assert isinstance(recovered, sf.Pipeline)
    stage = lowered(recovered)._stage_values()[0]
    assert isinstance(stage, FusionNode)
    assert type(stage.synthesizer) is FilterNode
    assert stage.synthesizer == _filter_by_judge()
    assert compile_candidate(recovered, operators=flow_operators()).url4 == url4
