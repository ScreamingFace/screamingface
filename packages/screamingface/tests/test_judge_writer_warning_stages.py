"""The judge-writer warning names the stages of the user's own Pipeline (E4b part 2, P2 #3).

FEATURE: ``Pipeline([Fusion(m, Reduce("context")), S, ...])`` is rewritten before compile: the
context Fusion and the stage after it become one Fusion. The ``sf.JudgeWriterWarning`` reads the
Pipeline as the user wrote it, so its stage numbers are the user's, and a judge stage that the
rewrite moves inside a Fusion still warns.
STORY: as a researcher, the warning points at the stages I can see in my own code.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators
from _nodes import FusionNode, JudgeNode, ReduceNode, VoteNode
from test_pipeline_compilation import _whole_candidate_benchmark

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.compilation import compile_evaluation
from screamingface.warnings import JudgeWriterWarning

_JUDGE_ROUTE = "openrouter/a/b"
_MEMBERS = ["provider/m1", "provider/m2", "provider/m3"]


def _message(first: int) -> str:
    second = first + 1
    return (
        f"Pipeline 'judged': stages {first} and {second} use the same model 'openrouter/a/b': "
        f"stage {first} scores the members as the judge, and stage {second} writes the answer, "
        "so the writer is also the scorer. Give one of the two stages another model, or keep "
        "both and ignore this warning."
    )


def _context() -> FusionNode:
    return FusionNode(["provider/a", "provider/b"], synthesizer=ReduceNode("context"))


def _judged_vote() -> FusionNode:
    vote = VoteNode(
        extract="last_number",
        normalize="numeric",
        weights=sf.signal("score:judge"),
        judge=JudgeNode(_JUDGE_ROUTE, returns="scores", rubric=RUBRIC),
    )
    return FusionNode(_MEMBERS, synthesizer=vote)


def _after_context_writer() -> sx.Pipeline:
    """The review repro: the user's stages 2 (judge) and 3 (writer).

    WHY 2, not 3: the context block form has one spelling since R11, ``sf.Fanout(m) >>
    sf.Synthesize(w)``, so the context Fusion and its writer are one stage of the chain.
    """

    return sx.Pipeline(
        [
            sx.Fanout(["provider/a", "provider/b"]) >> sx.Synthesize(sf.Model("provider/w")),
            sx.Fanout(_MEMBERS)
            >> sx.Judge(_JUDGE_ROUTE, rubric=RUBRIC)
            >> sx.Vote(over="last_number", normalize="numeric", weights="score:judge"),
            sf.Model(_JUDGE_ROUTE),
        ],
        name="judged",
    )


def _after_context() -> sf.Pipeline:
    """The judge Fusion follows the context Fusion, so the rewrite makes it its synthesizer.

    Group F (swap §5, deleted in 7f): it checks the context rewrite (``fusion_recipe.py``), and the
    new surface has no context stage that a judge stage can follow.
    """

    return sf.Pipeline([_context(), _judged_vote(), sf.Model(_JUDGE_ROUTE)], name="judged")


def _judge_writer_messages(recorded: pytest.WarningsRecorder) -> list[str]:
    return [str(w.message) for w in recorded if issubclass(w.category, JudgeWriterWarning)]


@pytest.mark.parametrize(
    ("build", "first"),
    [(_after_context_writer, 2), (_after_context, 2)],
    ids=["context-then-writer", "context-then-judge"],
)
def test_compile_names_the_users_stage_numbers(build: Callable[[], sf.Recipe], first: int) -> None:
    with pytest.warns(JudgeWriterWarning) as recorded:
        compile_candidate(build(), operators=flow_operators())

    assert _judge_writer_messages(recorded) == [_message(first)]
    judge_writer = [w for w in recorded if issubclass(w.category, JudgeWriterWarning)]
    assert judge_writer[0].filename == __file__


def test_evaluation_compile_names_the_users_stage_numbers() -> None:
    with pytest.warns(JudgeWriterWarning) as recorded:
        compile_evaluation(
            (_after_context_writer(),),
            _whole_candidate_benchmark(),
            1,
            operators=flow_operators(),
        )

    assert _judge_writer_messages(recorded) == [_message(2)]
