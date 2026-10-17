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

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_CN_I2 = (
    "sf.Consistency needs each Fusion member to be one sf.Model call; member 2 ('inner') is a "
    "nested Fusion or Pipeline"
)


def test_compile_refuses_a_non_model_member_with_the_fusion_error() -> None:
    inner = sf.Fusion(["prov/gamma", "prov/delta"], name="inner", synthesizer=sf.Vote())
    fusion = sf.Fusion(
        ["prov/alpha", "prov/beta"],
        name="cons",
        signals={"cons": sf.Consistency(n=2)},
        synthesizer=sf.Pick(by_signal=sf.signal("cons")),
    )
    # WHY bypass __init__: the Fusion check refuses this shape, so only a changed value reaches
    # the compiler with it.
    object.__setattr__(fusion, "members", (fusion.members[0], inner))

    with pytest.raises(ValueError) as caught:
        compile_candidate(fusion, operators=engine_operators())

    assert str(caught.value) == _CN_I2


def test_fusion_init_raises_the_same_cn_i2_error() -> None:
    # control: the message above is the one of Fusion.__init__
    inner = sf.Fusion(["prov/gamma", "prov/delta"], name="inner", synthesizer=sf.Vote())
    with pytest.raises(ValueError) as caught:
        sf.Fusion(
            ["prov/alpha", inner],
            name="cons",
            signals={"cons": sf.Consistency(n=2)},
            synthesizer=sf.Pick(by_signal=sf.signal("cons")),
        )

    assert str(caught.value) == _CN_I2
