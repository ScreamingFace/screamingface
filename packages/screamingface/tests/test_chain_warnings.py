"""The judge-writer warning on a chain (E4b surface unit 2, lowering §2.4, WJ-1).

FEATURE: the warning keeps today's text and names the stages of the chain the user wrote: a
closed block counts as one stage. It runs before the lowering, once per compile, and once per
evaluation (the evaluation entry lowers the values, so the compile does not warn again).
STORY: as a researcher, the warning points at the stages I can see in my own chain.
"""

from __future__ import annotations

import warnings

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators
from test_pipeline_compilation import _whole_candidate_benchmark

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.compilation import compile_evaluation
from screamingface._evaluation.model import _candidate_values
from screamingface.warnings import JudgeWriterWarning

_JUDGE_ROUTE = "openrouter/a/b"
_MEMBERS = ["provider/m1", "provider/m2", "provider/m3"]


def _message(name: str, first: int) -> str:
    second = first + 1
    return (
        f"Pipeline {name!r}: stages {first} and {second} use the same model 'openrouter/a/b': "
        f"stage {first} scores the members as the judge, and stage {second} writes the answer, "
        "so the writer is also the scorer. Give one of the two stages another model, or keep "
        "both and ignore this warning."
    )


def _judge_block() -> sf.Fusion:
    """A judge stage of today: unit 3 brings sf.Judge to the chain."""

    return sf.Fusion(_MEMBERS, synthesizer=sf.Judge(_JUDGE_ROUTE, returns="label", rubric=RUBRIC))


def _chain() -> sx.Pipeline:
    """Stage 1 is a closed block, stage 2 the judge, stage 3 the writer on the judge's model."""

    return sx.Pipeline(
        [
            sx.Fanout(["provider/a", "provider/b"]),
            sx.Synthesize("provider/s"),
            _judge_block(),
            sf.Model(_JUDGE_ROUTE),
        ],
        name="judged",
    )


def _messages(recorded: pytest.WarningsRecorder) -> list[str]:
    return [str(w.message) for w in recorded if issubclass(w.category, JudgeWriterWarning)]


def test_wj1_compile_names_the_users_chain_positions() -> None:
    with pytest.warns(JudgeWriterWarning) as recorded:
        compile_candidate(_chain(), operators=flow_operators())

    assert _messages(recorded) == [_message("judged", 2)]
    judge_writer = [w for w in recorded if issubclass(w.category, JudgeWriterWarning)]
    assert judge_writer[0].filename == __file__


def test_wj1_an_unnamed_chain_names_its_inferred_name() -> None:
    chain = (
        "provider/x"
        >> (sx.Fanout(["provider/a", "provider/b"]) >> sx.Vote())
        >> _judge_block()
        >> sf.Model(_JUDGE_ROUTE)
    )

    with pytest.warns(JudgeWriterWarning) as recorded:
        compile_candidate(chain, operators=flow_operators())

    assert _messages(recorded) == [_message("x->a+b->m1+m2+m3->b", 3)]


def test_wj1_the_evaluation_entry_warns_once_with_the_users_positions() -> None:
    with pytest.warns(JudgeWriterWarning) as recorded:
        values = _candidate_values(_chain())
        compile_evaluation(
            values,
            _whole_candidate_benchmark(),
            1,
            operators=flow_operators(),
            warn_judge_writers=False,
        )

    assert _messages(recorded) == [_message("judged", 2)]


def test_wj1_a_chain_with_another_writer_model_is_quiet() -> None:
    chain = sx.Pipeline(
        [sx.Fanout(["provider/a", "provider/b"]), sx.Vote(), _judge_block(), "provider/w"],
        name="judged",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", JudgeWriterWarning)
        compile_candidate(chain, operators=flow_operators())


def _narrowed_writer_block(writer: str) -> sx.Pipeline:
    """One user stage that lowers to two: Pipeline([Fusion(Rank by judge), writer])."""

    return (
        sx.Fanout(["provider/a", "provider/b"])
        >> sx.Judge(_JUDGE_ROUTE, rubric=RUBRIC)
        >> sx.Rank(1, by="score:judge")
        >> sx.Synthesize(writer)
    )


def test_e6_the_warning_numbers_the_users_stages_when_a_block_lowers_to_two() -> None:
    chain = sx.Pipeline(
        [
            _narrowed_writer_block("provider/w"),
            sx.Fanout(_MEMBERS) >> sx.JudgePick(_JUDGE_ROUTE, rubric=RUBRIC),
            sf.Model(_JUDGE_ROUTE),
        ],
        name="judged",
    )

    with pytest.warns(JudgeWriterWarning) as recorded:
        compile_candidate(chain, operators=flow_operators())

    # the lowered Pipeline has 4 stages (Fusion, writer, Fusion, writer); the user wrote 3
    assert _messages(recorded) == [_message("judged", 2)]


def test_e6_the_judge_and_writer_inside_one_block_still_warn() -> None:
    chain = sx.Pipeline(
        [sf.Model("provider/x"), _narrowed_writer_block(_JUDGE_ROUTE)], name="judged"
    )

    with pytest.warns(JudgeWriterWarning) as recorded:
        compile_candidate(chain, operators=flow_operators())

    assert _messages(recorded) == [_message("a+b->b", 1)]
