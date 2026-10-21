"""sf.Reduce("judge", judge=...) is the block form of sf.Judge (OME-1289, BK#4, 8S F3/F4).

FEATURE: a judge block and its named form compile to the same combine call and the same judge call.
INVARIANT: ``rubric=`` replaces the judge's rubric and is never stored, so the canonical block has
only ``judge``; equal blocks hash equal because ``sf.Judge`` is a hashable value.
"""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from _nodes import JudgeNode, ReduceNode, fusion_node

from screamingface._evaluation.candidate import compile_candidate
from screamingface.reducer import Reducer

_OVERRIDE = "Prefer the shortest correct answer."


def _url4(synthesizer: Reducer) -> str:
    fusion = fusion_node(members3(), synthesizer)
    return compile_candidate(fusion, operators=flow_operators()).url4


@pytest.mark.parametrize(
    ("returns", "params", "rubric"),
    [
        pytest.param("label", None, None, id="label-bare-same"),
        pytest.param("scores", {"temperature": 0}, _OVERRIDE, id="scores-params-override"),
    ],
)
def test_every_op_table_row_matches_its_named_form(
    returns: Any, params: dict[str, Any] | None, rubric: str | None
) -> None:
    judge = JudgeNode("provider/j", returns=returns, rubric=RUBRIC, params=params)
    named = JudgeNode("provider/j", returns=returns, rubric=rubric or RUBRIC, params=params)

    block = (
        ReduceNode("judge", judge=judge)
        if rubric is None
        else ReduceNode("judge", judge=judge, rubric=rubric)
    )

    assert _url4(block) == _url4(named)


def test_judge_block_canonical_form_equality_and_hash() -> None:
    judge = JudgeNode("provider/j", returns="scores", rubric=RUBRIC, params={"temperature": 0})
    plain = ReduceNode("judge", judge=judge)
    same = ReduceNode("judge", judge=judge, rubric=judge.rubric)

    assert same == plain
    assert hash(same) == hash(plain)
    assert len({same, plain}) == 1
    assert "rubric" not in same.options
    assert hash(judge) == hash(
        JudgeNode("provider/j", returns="scores", rubric=RUBRIC, params={"temperature": 0})
    )
    assert plain != ReduceNode("judge", judge=judge, rubric=_OVERRIDE)
    overridden = ReduceNode("judge", judge=judge, rubric=_OVERRIDE).options["judge"]
    assert isinstance(overridden, JudgeNode)
    assert overridden.rubric == _OVERRIDE
    assert plain._python() == f"sf.Reduce('judge', judge={judge._python()})"


def test_judge_block_rejects_a_bad_judge_or_rubric_or_mode() -> None:
    judge = JudgeNode("provider/j", returns="label", rubric=RUBRIC)

    with pytest.raises(TypeError, match="option 'judge' must be an sf.Judge"):
        ReduceNode("judge", judge="m")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="rubric"):
        ReduceNode("judge", judge=judge, rubric=3)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="rubric"):
        ReduceNode("judge", judge=judge, rubric=" ")
    with pytest.raises(ValueError, match="is a select op"):
        ReduceNode("judge", mode="compute", judge=judge)


def test_judge_equality_and_hash_keep_the_param_value_types() -> None:
    # True == 1 == 1.0 in Python, but a bool, an int and a float compile to different url4 text.
    judges = [
        JudgeNode("provider/j", returns="label", rubric=RUBRIC, params={"temperature": value})
        for value in (True, 1, 1.0)
    ]
    blocks = [ReduceNode("judge", judge=judge) for judge in judges]

    assert judges[0] != judges[1] != judges[2]
    assert judges[0] != judges[2]
    assert len({hash(judge) for judge in judges}) == 3
    assert blocks[0] != blocks[1] != blocks[2]
    assert blocks[0] != blocks[2]
    assert len(set(blocks)) == 3
    assert len({_url4(judge) for judge in judges}) == 3
    twin = JudgeNode("provider/j", returns="label", rubric=RUBRIC, params={"temperature": 1})
    assert twin == judges[1]
    assert hash(twin) == hash(judges[1])
    assert _url4(twin) == _url4(judges[1])
