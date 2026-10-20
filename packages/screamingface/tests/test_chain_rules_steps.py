"""The chain rules that need a judge or a narrow step (E4b surface unit 3, surface §2.2).

FEATURE: a block is ``Fanout``, then at most one ``Judge``, then 0–4 narrow steps, then one
reduce or write step. A ``Judge`` needs a step that reads ``score:judge`` (CH-10). Until the narrow
compile (unit 5), a block that needs the spec ``narrow`` key is refused (CH-12).
STORY: as a researcher, a wrong order of judge, narrow and terminal steps fails at the ``>>``, with
a message that says what to do.
"""

from __future__ import annotations

import pytest

import screamingface as sf
from screamingface import _surface as sx
from screamingface._surface.chain import _Block
from screamingface._surface.lowering import lower

_PAIR = ["provider/a", "provider/b"]
_JUDGE = "provider/judge"
_RUBRIC = "Give a higher number to a more correct answer."


def _judge() -> sx.Judge:
    return sx.Judge(_JUDGE, rubric=_RUBRIC)


def _today_judge(**options: object) -> sf.Judge:
    return sf.Judge(_JUDGE, returns="scores", rubric=_RUBRIC, **options)  # type: ignore[arg-type]


# ---------------------------------------------------------------- CH-3


def test_ch3_a_second_judge_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match=r"^a block takes one judge: sf\.Judge and sf\.JudgePick use the same judge signal$",
    ):
        _ = sx.Fanout(_PAIR) >> _judge() >> _judge()


def test_ch3_a_judge_pick_after_a_judge_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match=r"^a block takes one judge: sf\.Judge and sf\.JudgePick use the same judge signal$",
    ):
        _ = sx.Fanout(_PAIR) >> _judge() >> sx.JudgePick(_JUDGE, rubric="Pick one.")


def test_ch3_a_judge_pick_after_a_judge_and_a_narrow_step_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match=r"^a block takes one judge: sf\.Judge and sf\.JudgePick use the same judge signal$",
    ):
        _ = (
            sx.Fanout(_PAIR)
            >> _judge()
            >> sx.Rank(1, by="score:judge")
            >> sx.JudgePick(_JUDGE, rubric="Pick one.")
        )


def test_ch2_a_recipe_after_a_judge_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match=r"^a sf\.Fanout block needs a reducer or sf\.Synthesize before the next stage$",
    ):
        _ = sx.Fanout(_PAIR) >> _judge() >> sf.Model("provider/x")


# ---------------------------------------------------------------- CH-4


def test_ch4_a_fifth_narrow_step_is_refused() -> None:
    chain = sx.Fanout(_PAIR) >> sx.Rank(2, by="cost_usd")
    for _ in range(3):
        chain = chain >> sx.Rank(2, by="cost_usd")

    with pytest.raises(ValueError, match=r"^a block takes at most 4 narrow steps$"):
        _ = chain >> sx.Rank(2, by="cost_usd")


# ---------------------------------------------------------------- CH-5


@pytest.mark.parametrize(
    "following",
    [sf.Model("provider/x"), "provider/x", sx.Fanout(_PAIR), sx.Fanout(_PAIR) >> sx.Vote()],
    ids=["model", "route", "fanout", "closed-block"],
)
def test_ch5_a_selection_goes_to_a_writer_a_reducer_or_a_narrow_step(
    following: str | sf.Recipe | sx.Fanout,
) -> None:
    with pytest.raises(
        ValueError,
        match=r"^a selection goes to sf\.Synthesize, a reducer, or another narrow step$",
    ):
        _ = sx.Fanout(_PAIR) >> sx.Rank(1, by="cost_usd") >> following


# ---------------------------------------------------------------- CH-6


def test_ch6_a_judge_after_a_narrow_step_is_refused() -> None:
    with pytest.raises(ValueError, match=r"^sf\.Judge comes right after sf\.Fanout$"):
        _ = sx.Fanout(_PAIR) >> sx.Rank(1, by="cost_usd") >> _judge()


# ---------------------------------------------------------------- CH-7


@pytest.mark.parametrize(
    "following",
    [sx.Vote(), sx.Rank(1, by="cost_usd"), sf.Model("provider/x"), sx.Concat(), _judge()],
    ids=["reducer", "narrow", "model", "concat", "judge"],
)
def test_ch7_concat_must_be_followed_by_synthesize(following: object) -> None:
    with pytest.raises(ValueError, match=r"^sf\.Concat must be followed by sf\.Synthesize$"):
        _ = sx.Fanout(_PAIR) >> sx.Concat() >> following  # type: ignore[operator]


def test_concat_then_synthesize_is_a_block() -> None:
    chain = sx.Fanout(_PAIR) >> sx.Concat() >> sx.Synthesize("provider/w")

    assert lower(chain) == sf.Pipeline([sf.Fusion(_PAIR, synthesizer=sf.Concat()), "provider/w"])


# ---------------------------------------------------------------- CH-10


@pytest.mark.parametrize(
    "terminal",
    [sx.Vote(), sx.Median(), sx.ArgMax("cost_usd"), sx.Synthesize("provider/w")],
    ids=["vote", "median", "argmax-cost", "synthesize"],
)
def test_ch10_a_judge_that_no_step_reads_is_refused(terminal: sx.Vote) -> None:
    with pytest.raises(
        ValueError, match=r"^sf\.Judge scores the members, but no step reads score:judge$"
    ):
        _ = sx.Fanout(_PAIR) >> _judge() >> terminal


def test_ch10_a_judge_read_only_by_a_narrow_step_is_read() -> None:
    chain = sx.Fanout(_PAIR) >> _judge() >> sx.Rank(1, by="score:judge") >> sx.Synthesize("p/w")

    assert lower(chain) == sf.Pipeline(
        [sf.Fusion(_PAIR, synthesizer=sf.Rank(k=1, by=_today_judge())), "p/w"]
    )


@pytest.mark.parametrize(
    "steps",
    [
        [sx.ArgMax("score:judge")],
        [sx.ArgMin("score:judge")],
        [sx.Vote(weights="score:judge")],
        [sx.Rank(1, by="score:judge"), sx.Synthesize("provider/w")],
        [sx.Filter(where=sf.signal("score:judge") >= 7), sx.Synthesize("provider/w")],
    ],
    ids=["argmax", "argmin", "vote", "rank", "filter"],
)
def test_ch10_a_score_judge_read_with_no_judge_is_refused(steps: list[sx.Vote]) -> None:
    with pytest.raises(
        ValueError, match=r"^score:judge needs sf\.Judge\(\.\.\.\) after sf\.Fanout$"
    ):
        sx.Pipeline([sx.Fanout(_PAIR), *steps])


# ---------------------------------------------------------------- CH-12


@pytest.mark.parametrize(
    "steps",
    [
        [sx.Filter(where=sf.signal("cost_usd") < 1), sx.Mean()],
        [sx.Rank(1, by="cost_usd"), sx.Vote()],
        [sx.Rank(2, by="cost_usd"), sx.Filter(where=sf.matches("x")), sx.Synthesize("p/w")],
        [sx.Rank(2, by="cost_usd"), sx.Concat(), sx.Synthesize("p/w")],
    ],
    ids=["filter-mean", "rank-vote", "two-before-synthesize", "rank-concat"],
)
def test_ch12_a_block_that_needs_the_narrow_key_is_refused(steps: list[sx.Vote]) -> None:
    with pytest.raises(ValueError, match=r"^narrow before a reducer is not built yet$"):
        sx.Pipeline([sx.Fanout(_PAIR), *steps])


# ---------------------------------------------------------------- the block record


def test_a_block_records_its_judge_and_its_narrow_steps() -> None:
    chain = sx.Fanout(_PAIR) >> _judge() >> sx.Rank(1, by="score:judge") >> sx.Synthesize("p/w")

    (block,) = chain._stages
    assert isinstance(block, _Block)
    assert block.judge == _judge()
    assert block.narrow == (sx.Rank(1, by="score:judge"),)
    assert block.terminal == sx.Synthesize("p/w")
    assert block.name == "a+b->w"
    assert chain.name == "a+b->w"


def test_a_block_with_a_writer_after_a_narrow_step_is_one_stage() -> None:
    narrowed = sx.Fanout(_PAIR) >> sx.Rank(1, by="cost_usd") >> sx.Synthesize("provider/w")
    chain = "provider/x" >> narrowed >> sf.Model("provider/y")

    assert len(chain._stages) == 3
    assert lower(chain) == sf.Pipeline(
        [
            "provider/x",
            sf.Fusion(_PAIR, synthesizer=sf.Rank(k=1, by_signal=sf.signal("cost_usd"))),
            "provider/w",
            "provider/y",
        ]
    )


def test_an_optional_narrowed_block_moves_the_flag_to_its_pipeline() -> None:
    chain = sx.Pipeline(
        [sx.Fanout(_PAIR), sx.Rank(1, by="cost_usd"), sx.Synthesize("provider/w")], optional=True
    )

    assert lower(chain) == sf.Pipeline(
        [sf.Fusion(_PAIR, synthesizer=sf.Rank(k=1, by_signal=sf.signal("cost_usd"))), "provider/w"],
        optional=True,
    )
