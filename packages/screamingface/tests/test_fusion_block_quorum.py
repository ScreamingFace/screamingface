"""The Fusion block form keeps quorum and optional members (OME-1289 E4a x OME-1557).

FEATURE: ``Pipeline([Fusion(m, Reduce("context"), quorum=…), Model])`` lowers to
``Fusion(m, Model, quorum=…)`` and compiles to the same url4; a Fusion whose member the rewrite
changes keeps its own quorum and optional flag, and an optional Pipeline member stays optional.
INVARIANT defended: the block form never drops a failure policy, so it never turns an optional
member into a required one.
"""

from __future__ import annotations

from _reducer_fixtures import fixture_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_MEMBERS = ["provider/a", "provider/b", sf.Model("provider/c", optional=True)]


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=fixture_operators()).url4


def test_the_block_form_with_quorum_compiles_to_the_named_form() -> None:
    block = sf.Pipeline(
        [
            sf.Fusion(_MEMBERS, synthesizer=sf.Reduce("context"), quorum=2),
            sf.Model("provider/s"),
        ]
    )
    named = sf.Fusion(_MEMBERS, synthesizer="provider/s", quorum=2)

    assert _url4(block) == _url4(named)


def test_a_rewritten_fusion_member_keeps_its_quorum() -> None:
    inner = sf.Pipeline(
        [sf.Fusion(["provider/a", "provider/b"], synthesizer=sf.Reduce("context")), "provider/s"]
    )
    outer = sf.Fusion([inner, sf.Model("provider/c", optional=True)], synthesizer="p/t", quorum=1)
    expected = sf.Fusion(
        [
            sf.Fusion(["provider/a", "provider/b"], synthesizer="provider/s"),
            sf.Model("provider/c", optional=True),
        ],
        synthesizer="p/t",
        quorum=1,
    )

    assert _url4(outer) == _url4(expected)


def test_an_optional_block_form_member_stays_optional() -> None:
    pair = ["provider/a", "provider/b"]
    block = sf.Fusion(
        [
            "provider/x",
            sf.Pipeline(
                [sf.Fusion(pair, synthesizer=sf.Reduce("context")), "provider/s"], optional=True
            ),
        ],
        synthesizer="provider/t",
        quorum=1,
    )
    named = sf.Fusion(
        ["provider/x", sf.Fusion(pair, synthesizer="provider/s", optional=True)],
        synthesizer="provider/t",
        quorum=1,
    )

    assert _url4(block) == _url4(named)
    assert ";optional" in _url4(block)
