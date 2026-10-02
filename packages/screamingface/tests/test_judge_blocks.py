"""sf.Reduce("judge", judge=...) is the block form of sf.Judge (OME-1289, BK#4, 8S F3/F4).

FEATURE: a judge block and its named form compile to the same combine call and the same judge call.
INVARIANT: ``rubric=`` replaces the judge's rubric and is never stored, so the canonical block has
only ``judge``; equal blocks hash equal because ``sf.Judge`` is a hashable value.
"""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.blocks import _BLOCK_FORMS, _BlockForm
from screamingface.judge import Judge, _with_rubric
from screamingface.reducer import Reducer

_OVERRIDE = "Prefer the shortest correct answer."


def _url4(synthesizer: Reducer) -> str:
    fusion = sf.Fusion(members3(), synthesizer=synthesizer)
    return compile_candidate(fusion, operators=flow_operators()).url4


@pytest.mark.parametrize("rubric", [None, _OVERRIDE], ids=["same", "override"])
@pytest.mark.parametrize("params", [None, {"temperature": 0}], ids=["bare", "params"])
@pytest.mark.parametrize("returns", ["label", "scores"])
def test_every_op_table_row_matches_its_named_form(
    returns: Any, params: dict[str, Any] | None, rubric: str | None
) -> None:
    judge = sf.Judge("provider/j", returns=returns, rubric=RUBRIC, params=params)
    named = sf.Judge("provider/j", returns=returns, rubric=rubric or RUBRIC, params=params)

    block = (
        sf.Reduce("judge", judge=judge)
        if rubric is None
        else sf.Reduce("judge", judge=judge, rubric=rubric)
    )

    assert _url4(block) == _url4(named)


def test_judge_block_canonical_form_equality_and_hash() -> None:
    judge = sf.Judge("provider/j", returns="scores", rubric=RUBRIC, params={"temperature": 0})
    plain = sf.Reduce("judge", judge=judge)
    same = sf.Reduce("judge", judge=judge, rubric=judge.rubric)

    assert same == plain
    assert hash(same) == hash(plain)
    assert len({same, plain}) == 1
    assert "rubric" not in same.options
    assert hash(judge) == hash(
        sf.Judge("provider/j", returns="scores", rubric=RUBRIC, params={"temperature": 0})
    )
    assert plain != sf.Reduce("judge", judge=judge, rubric=_OVERRIDE)
    overridden = sf.Reduce("judge", judge=judge, rubric=_OVERRIDE).options["judge"]
    assert isinstance(overridden, Judge)
    assert overridden.rubric == _OVERRIDE
    assert eval(plain._python(), {"sf": sf}) == plain  # noqa: S307 - our own generated code
    assert plain._python() == f"sf.Reduce('judge', judge={judge._python()})"


def test_judge_block_rejects_a_bad_judge_or_rubric_or_mode() -> None:
    judge = sf.Judge("provider/j", returns="label", rubric=RUBRIC)

    with pytest.raises(TypeError, match="option 'judge' must be an sf.Judge"):
        sf.Reduce("judge", judge="m")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="rubric"):
        sf.Reduce("judge", judge=judge, rubric=3)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="rubric"):
        sf.Reduce("judge", judge=judge, rubric=" ")
    with pytest.raises(ValueError, match="is a select op"):
        sf.Reduce("judge", mode="compute", judge=judge)


def test_a_registered_block_form_wraps_a_named_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(options: Any) -> Reducer:
        raise ValueError("the named form says no")

    monkeypatch.setitem(_BLOCK_FORMS, "judge", _BlockForm(build=refuse, options=lambda named: {}))
    judge = sf.Judge("provider/j", returns="label", rubric=RUBRIC)

    with pytest.raises(ValueError, match=r"sf\.Reduce\('judge'\): the named form says no"):
        sf.Reduce("judge", judge=judge)


def test_the_judge_block_form_is_registered_and_keeps_a_judge_unchanged_without_a_rubric() -> None:
    judge = sf.Judge("provider/j", returns="label", rubric=RUBRIC)

    assert isinstance(_BLOCK_FORMS["judge"].build({"judge": judge}), Judge)
    assert _with_rubric(judge, None) is judge
    assert _with_rubric(judge, _OVERRIDE) == sf.Judge(
        "provider/j", returns="label", rubric=_OVERRIDE
    )


def test_judge_equality_and_hash_keep_the_param_value_types() -> None:
    # True == 1 == 1.0 in Python, but a bool, an int and a float compile to different url4 text.
    judges = [
        sf.Judge("provider/j", returns="label", rubric=RUBRIC, params={"temperature": value})
        for value in (True, 1, 1.0)
    ]
    blocks = [sf.Reduce("judge", judge=judge) for judge in judges]

    assert judges[0] != judges[1] != judges[2]
    assert judges[0] != judges[2]
    assert len({hash(judge) for judge in judges}) == 3
    assert blocks[0] != blocks[1] != blocks[2]
    assert blocks[0] != blocks[2]
    assert len(set(blocks)) == 3
    assert len({_url4(judge) for judge in judges}) == 3
    twin = sf.Judge("provider/j", returns="label", rubric=RUBRIC, params={"temperature": 1})
    assert twin == judges[1]
    assert hash(twin) == hash(judges[1])
    assert _url4(twin) == _url4(judges[1])
