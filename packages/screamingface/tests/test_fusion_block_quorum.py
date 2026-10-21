"""The Fusion block form keeps quorum and optional members (OME-1289 E4a x OME-1557).

FEATURE: ``Pipeline([Fusion(m, Reduce("context"), quorum=…), Model])`` lowers to
``Fusion(m, Model, quorum=…)`` and compiles to the same url4; a Fusion whose member the rewrite
changes keeps its own quorum and optional flag, and an optional Pipeline member stays optional.
INVARIANT defended: the block form never drops a failure policy, so it never turns an optional
member into a required one.
"""

# group F (7f): the context block form (an internal ReduceNode("context") then a writer stage) is
# deleted code (D7-8); the block side builds it from the internal nodes until then.

from __future__ import annotations

from _nodes import ReduceNode, fusion_node
from _reducer_fixtures import fixture_operators

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate

_MEMBERS = ["provider/a", "provider/b", sf.Model("provider/c", optional=True)]


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=fixture_operators()).url4


def test_the_block_form_with_quorum_compiles_to_the_named_form() -> None:
    block = sf.Pipeline(
        [fusion_node(_MEMBERS, ReduceNode("context"), quorum=2), sf.Model("provider/s")]
    )
    named = sx.Fanout(_MEMBERS, quorum=2) >> sx.Synthesize("provider/s")

    assert _url4(block) == _url4(named)


def test_a_rewritten_fusion_member_keeps_its_quorum() -> None:
    inner = sf.Pipeline(
        [fusion_node(["provider/a", "provider/b"], ReduceNode("context")), "provider/s"]
    )
    outer = sx.Fanout([inner, sf.Model("provider/c", optional=True)], quorum=1) >> sx.Synthesize(
        "p/t"
    )
    expected = sx.Fanout(
        [
            sx.Fanout(["provider/a", "provider/b"]) >> sx.Synthesize("provider/s"),
            sf.Model("provider/c", optional=True),
        ],
        quorum=1,
    ) >> sx.Synthesize("p/t")

    assert _url4(outer) == _url4(expected)


def test_an_optional_block_form_member_stays_optional() -> None:
    pair = ["provider/a", "provider/b"]
    block = sx.Fanout(
        [
            "provider/x",
            sf.Pipeline([fusion_node(pair, ReduceNode("context")), "provider/s"], optional=True),
        ],
        quorum=1,
    ) >> sx.Synthesize("provider/t")
    named = sx.Fanout(
        ["provider/x", sx.Pipeline([sx.Fanout(pair), sx.Synthesize("provider/s")], optional=True)],
        quorum=1,
    ) >> sx.Synthesize("provider/t")

    assert _url4(block) == _url4(named)
    assert ";optional" in _url4(block)
