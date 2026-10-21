"""A Rank or Concat Fusion hands a selection only to the NEXT Pipeline stage (OME-1289)."""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from _nodes import ConcatNode, FusionNode, JudgeNode, RankNode, fusion_node
from url4 import Expression, RelExpr, Source, build

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate

_SURFACE = _CheckSurface(
    check_route="/benchmarks/ifeval/revision-1/check-surface",
    feedback_intent="feedback",
    expected_check_cost="free",
)


def _compile(recipe: sf.Recipe) -> Any:
    return compile_candidate(recipe, check_surface=_SURFACE, operators=flow_operators())


# WHY internal nodes: a selection block with no stage after it is the value these compile checks
# guard; the surface refuses it when the chain is built (``sx.Fanout(...) >> sx.Rank(...)`` alone).
def _rank() -> FusionNode:
    return fusion_node(members3(), RankNode(k=2, by_signal=sf.signal("field:score")))


def _rank_by_judge() -> FusionNode:
    judge = JudgeNode("provider/j", returns="scores", rubric=RUBRIC)
    return fusion_node(members3(), RankNode(k=2, by=judge))


def _concat() -> FusionNode:
    return fusion_node(members3(), ConcatNode())


def _writer() -> sf.Model:
    return sf.Model("provider/w", prompt="Write the final answer from these drafts.")


def _calls(url4: str) -> dict[str, RelExpr]:
    root = build(url4)
    assert isinstance(root, Expression)
    return {
        source.name: source.value
        for source in root.sources
        if isinstance(source, Source)
        and source.name is not None
        and isinstance(source.value, RelExpr)
    }


def test_selection_at_end_of_candidate_raises_at_compile() -> None:
    with pytest.raises(ValueError, match="a Rank must be followed by another stage"):
        _compile(_rank())
    with pytest.raises(ValueError, match="a Rank must be followed by another stage"):
        _compile(_rank_by_judge())
    with pytest.raises(ValueError, match="a Concat must be followed by another stage"):
        _compile(_concat())
    with pytest.raises(ValueError, match="a Concat must be followed by another stage"):
        _compile(sf.Pipeline(["provider/x", _concat()]))
    with pytest.raises(ValueError, match="a Rank must be followed by another stage"):
        _compile(sf.Pipeline([sf.Pipeline(["provider/x", _rank()])]))
    # a Fusion whose Recipe synthesizer ends in a selection ends the candidate with it
    with pytest.raises(ValueError, match="a Rank must be followed by another stage"):
        _compile(
            sf.Fanout(members3()) >> sf.Synthesize(sf.Pipeline(["provider/y", _rank()])),
        )
    message = r"'a\+b\+c' ends the candidate with a selection"
    with pytest.raises(ValueError, match=message):
        _compile(_rank())


def test_selection_as_fusion_or_loop_member_raises_at_compile() -> None:
    member = "a Rank Fusion cannot be a Fusion member"
    with pytest.raises(ValueError, match=member):
        _compile(sf.Fanout([_rank(), "provider/d"]) >> sf.Synthesize("provider/s"))
    with pytest.raises(ValueError, match="a Concat Fusion cannot be a Fusion member"):
        _compile(sf.Fanout(["provider/d", _concat()]) >> sf.Vote())
    # also through a Pipeline that ends in a selection
    with pytest.raises(ValueError, match="a Concat Fusion cannot be a Fusion member"):
        _compile(
            sf.Fanout([sf.Pipeline(["provider/x", _concat()]), "provider/d"])
            >> sf.Synthesize("p/s")
        )
    # the check does not depend on the synthesizer kind
    with pytest.raises(ValueError, match=member):
        _compile(sf.Fanout([_rank_by_judge(), "provider/d"]) >> sf.Vote())

    feed = "a Rank cannot feed a corrective loop"
    with pytest.raises(ValueError, match=feed):
        _compile(sf.CorrectiveLoop([_rank(), "provider/d"], judge="provider/j"))
    with pytest.raises(ValueError, match=feed):
        _compile(sf.SelfCorrective(sf.Pipeline(["provider/x", _rank()])))
    with pytest.raises(ValueError, match="a Concat cannot feed a corrective loop"):
        _compile(sf.CorrectiveLoop(["provider/d", sf.Pipeline([_concat()])], judge="provider/j"))


def test_a_fusion_whose_recipe_synthesizer_ends_in_a_selection_is_not_a_member() -> None:
    ends_in_rank = sf.Fanout(members3()) >> sf.Synthesize(sf.Pipeline(["provider/y", _rank()]))

    with pytest.raises(ValueError, match="a Rank Fusion cannot be a Fusion member"):
        _compile(sf.Fanout([ends_in_rank, "provider/d"]) >> sf.Synthesize("provider/s"))
    # followed by a stage, the same Fusion is an ordinary member
    followed = sf.Pipeline([ends_in_rank, _writer()])
    assert _compile(sf.Fanout([followed, "provider/d"]) >> sf.Synthesize("provider/s")).operations


def test_a_selection_that_is_followed_compiles_everywhere_it_may_stand() -> None:
    followed = sf.Fanout(members3()) >> sf.Rank(2, by="field:score") >> sf.Synthesize(_writer())
    # a selection inside a Pipeline's first stage, followed by a Fusion
    again = sf.Pipeline([_concat(), sf.Fanout(["provider/d", "provider/e"]) >> sf.Vote()])
    # a followed selection may be a member, and a corrective loop member, once a stage follows it
    nested = sf.Fanout([followed, "provider/d"]) >> sf.Synthesize("provider/s")
    loop = sf.CorrectiveLoop([followed, "provider/d"], judge="provider/j", max_rounds=2)
    solo = sf.SelfCorrective(followed, max_rounds=2)

    for recipe in (followed, again, nested, loop, solo):
        assert _compile(recipe).operations
    assert _compile(sf.Pipeline([_rank(), _concat(), _writer()])).operations


def test_next_stage_context_is_selection_only() -> None:
    compiled = _compile(
        sf.Fanout(members3())
        >> sf.Judge("provider/j", rubric=RUBRIC)
        >> sf.Rank(2, by="score:judge")
        >> sf.Synthesize(_writer())
    )
    calls = _calls(compiled.url4)

    # the panel is members 1 to 3, judge_1 and synthesis_1, so the writer is model_4
    assert calls["model_4"].path == "/provider/w"
    assert calls["model_4"].context == "$synthesis_1"
    assert [operation.id for operation in compiled.operations][-2:] == [
        "op_synthesis_1",
        "op_model_4",
    ]
    assert compiled.operations[-1].depends_on == ("op_synthesis_1",)

    concat = _calls(_compile(sf.Fanout(members3()) >> sf.Concat() >> sf.Synthesize(_writer())).url4)
    assert concat["model_4"].context == "$synthesis_1"
