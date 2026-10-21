"""The compile-time CN-I2 check of a Consistency Fusion (E4b part 7, review P7 #7).

FEATURE: ``sf.Fusion`` refuses ``sf.Consistency`` over a member that is not one ``sf.Model``
(CN-I2); the compiler repeats the check before it builds the sample calls.
STORY: as a researcher whose Fusion was changed after its checks ran, I get the same
``ValueError`` as from ``sf.Fusion``, never a bare ``AssertionError`` (or, under ``python -O``,
sample calls for a member that has no model).
INVARIANT defended: the compiler's CN-I2 check raises the type and the message of the
``Fusion.__init__`` check, also when ``__init__`` is bypassed.
"""

from __future__ import annotations

import pytest
from _combine_contract import engine_operators
from _nodes import FusionNode

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._surface.lowering import lower

_CN_I2 = (
    "sf.Consistency needs each Fusion member to be one sf.Model call; member 2 ('inner') is a "
    "nested Fusion or Pipeline"
)


def test_compile_refuses_a_non_model_member_with_the_fusion_error() -> None:
    inner = sf.Fanout(["prov/gamma", "prov/delta"], name="inner") >> sf.Vote()
    fusion = lower(
        sf.Fanout(["prov/alpha", "prov/beta"], signals={"cons": sf.Consistency(n=2)}, name="cons")
        >> sf.ArgMax("cons")
    )
    assert isinstance(fusion, FusionNode)
    # WHY bypass __init__: the Fusion check refuses this shape, so only a changed value reaches
    # the compiler with it. The lowered node is the value the compiler reads.
    object.__setattr__(fusion, "members", (fusion.members[0], lower(inner)))

    with pytest.raises(ValueError) as caught:
        compile_candidate(fusion, operators=engine_operators())

    assert str(caught.value) == _CN_I2


def test_fusion_init_raises_the_same_cn_i2_error() -> None:
    # control: the message above is the one of Fusion.__init__
    inner = sf.Fanout(["prov/gamma", "prov/delta"], name="inner") >> sf.Vote()
    with pytest.raises(ValueError) as caught:
        _ = sf.Fanout(
            ["prov/alpha", inner], signals={"cons": sf.Consistency(n=2)}, name="cons"
        ) >> sf.ArgMax("cons")

    assert str(caught.value) == _CN_I2
