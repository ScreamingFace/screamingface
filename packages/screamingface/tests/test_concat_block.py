"""The concat block compiles to the same url4 as sf.Concat (OME-1289 gap, BK#4)."""

from __future__ import annotations

import pytest
from _combine_flow_fixtures import flow_operators, members3

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.reducer import Reducer

_DEFAULT = sf.Concat().separator


def _url4(reducer: Reducer) -> str:
    # a selection must be followed by another stage, so the Fusion is wrapped
    recipe = sf.Pipeline([sf.Fusion(members3(), synthesizer=reducer), "provider/next"])
    return compile_candidate(recipe, operators=flow_operators()).url4


@pytest.mark.parametrize(
    ("block", "named"),
    [
        (sf.Reduce("concat"), sf.Concat()),
        (
            sf.Reduce("concat", separator="\n--\n", label=False),
            sf.Concat("\n--\n", label=False),
        ),
        (sf.Reduce("concat", separator="||"), sf.Concat("||")),
        (sf.Reduce("concat", label=False), sf.Concat(label=False)),
        (sf.Reduce("concat", separator="$|\x7f"), sf.Concat("$|\x7f")),
    ],
    ids=["default", "both options", "separator", "no labels", "odd separator"],
)
def test_reduce_concat_block_equals_sf_concat(block: sf.Reduce, named: sf.Concat) -> None:
    assert _url4(block) == _url4(named)
    assert block._plan() == named._plan()


def test_reduce_concat_block_canonical_form_equality_and_hash() -> None:
    plain = sf.Reduce("concat")

    # the defaults are not stored, so every spelling of the default is one block
    for same in (
        sf.Reduce("concat", separator=_DEFAULT),
        sf.Reduce("concat", label=True),
        sf.Reduce("concat", separator=_DEFAULT, label=True),
    ):
        assert same == plain
        assert hash(same) == hash(plain)
        assert dict(same.options) == {}
    assert dict(sf.Reduce("concat", label=False).options) == {"label": False}
    assert dict(sf.Reduce("concat", separator="|").options) == {"separator": "|"}
    assert sf.Reduce("concat", separator="|") != plain
    assert sf.Reduce("concat", label=False) != plain
    for block in (plain, sf.Reduce("concat", separator="|", label=False)):
        twin = eval(block._python(), {"sf": sf})  # noqa: S307
        assert twin == block
        assert hash(twin) == hash(block)


def test_reduce_concat_block_validation() -> None:
    with pytest.raises(ValueError, match="option 'separator' must be 1 to 1024 characters"):
        sf.Reduce("concat", separator="")
    with pytest.raises(TypeError, match="option 'label' must be a bool"):
        sf.Reduce("concat", label=1)
    with pytest.raises(ValueError, match="does not take option 'k'"):
        sf.Reduce("concat", k=2)
    with pytest.raises(ValueError, match="is a compute op, not select"):
        sf.Reduce("concat", mode="select")
    # a selection still cannot end a candidate, and the message names the block
    with pytest.raises(ValueError, match=r"a Reduce\('concat'\) must be followed by another stage"):
        compile_candidate(
            sf.Fusion(members3(), synthesizer=sf.Reduce("concat")), operators=flow_operators()
        )
