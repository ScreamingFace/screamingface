"""The chain rules of the map → select → reduce surface (E4b surface unit 2, surface §2).

FEATURE: ``a >> b`` builds one chain, read left to right. A ``sf.Fanout`` opens a block; a
reducer or ``sf.Synthesize`` closes it. Each refusal has its rule id (``CH-n``) and its message,
and raises at construction or at the ``>>`` that closes the block, never after a model call.
STORY: as a researcher, I write ``sf.Fanout(models) >> sf.Vote()`` and a wrong order fails at once
with a message that says what to do.
"""

from __future__ import annotations

import pytest

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import _candidate_values
from screamingface._surface.chain import Step, _Block
from screamingface._surface.lowering import lower

_PAIR = ["provider/a", "provider/b"]
_TRIO = ["provider/a", "provider/b", "provider/c"]
_OPEN = "the chain ends inside a sf.Fanout block: add a reducer or sf.Synthesize"
_CH2 = "a sf.Fanout block needs a reducer or sf.Synthesize before the next stage"


def _block() -> sx.Pipeline:
    return sx.Fanout(_PAIR) >> sx.Vote()


# ---------------------------------------------------------------- >> and sf.Pipeline


def test_rshift_builds_the_explicit_pipeline() -> None:
    assert sx.Fanout(_PAIR) >> sx.Vote() == sx.Pipeline([sx.Fanout(_PAIR), sx.Vote()])


def test_rshift_is_read_left_to_right() -> None:
    chain = sx.Fanout(_PAIR) >> sx.Vote() >> sf.Model("provider/after")

    assert chain == sx.Pipeline([sx.Fanout(_PAIR), sx.Vote(), sf.Model("provider/after")])
    assert chain.steps == (sx.Fanout(_PAIR), sx.Vote(), sf.Model("provider/after"))


def test_a_route_string_on_the_left_works_through_rrshift() -> None:
    chain = "provider/first" >> sx.Fanout(_PAIR) >> sx.Vote()

    assert chain == sx.Pipeline([sf.Model("provider/first"), sx.Fanout(_PAIR), sx.Vote()])


def test_a_model_on_the_left_works_through_rrshift() -> None:
    chain = sf.Model("provider/first") >> _block()

    assert chain == sx.Pipeline(["provider/first", sx.Fanout(_PAIR), sx.Vote()])


def test_an_unnamed_nested_pipeline_is_flattened() -> None:
    nested = sx.Pipeline([sx.Pipeline(["provider/x", sx.Fanout(_PAIR)]), sx.Vote()])

    assert nested == sx.Pipeline(["provider/x", sx.Fanout(_PAIR), sx.Vote()])
    assert lower(nested) == lower(sx.Pipeline(["provider/x", sx.Fanout(_PAIR), sx.Vote()]))


def test_a_named_nested_pipeline_keeps_its_grouping() -> None:
    group = sx.Pipeline(["provider/x", sx.Fanout(_PAIR), sx.Vote()], name="group")
    chain = group >> sf.Model("provider/after")

    assert chain.steps == (group, sf.Model("provider/after"))
    assert lower(chain) == sf.Pipeline(
        [
            sf.Pipeline(
                ["provider/x", sf.Fusion(_PAIR, synthesizer=sf.Vote())],
                name="group",
            ),
            "provider/after",
        ]
    )


def test_a_closed_block_is_recorded_as_a_block() -> None:
    chain = "provider/x" >> _block()

    (model, block) = chain._stages
    assert model == sf.Model("provider/x")
    assert isinstance(block, _Block)
    assert block.fanout == sx.Fanout(_PAIR)
    assert block.judge is None
    assert block.narrow == ()
    assert block.terminal == sx.Vote()
    assert block.node == sf.Fusion(_PAIR, synthesizer=sf.Vote())


def test_an_empty_pipeline_is_refused() -> None:
    with pytest.raises(ValueError, match="a Pipeline requires at least one stage"):
        sx.Pipeline([])


def test_the_steps_must_be_a_sequence() -> None:
    with pytest.raises(TypeError, match="Pipeline stages must be an ordered sequence"):
        sx.Pipeline("provider/x")  # type: ignore[arg-type]


def test_an_optional_unnamed_chain_is_not_a_stage() -> None:
    optional = sx.Pipeline([sx.Fanout(_PAIR), sx.Vote()], optional=True)

    with pytest.raises(ValueError, match="optional=True is only supported on Fusion members"):
        _ = optional >> sf.Model("provider/after")


# ---------------------------------------------------------------- CH-1


@pytest.mark.parametrize(
    "step",
    [sx.Vote(), sx.Median(), sx.Mean(), sx.Synthesize("provider/w")],
    ids=["vote", "median", "mean", "synthesize"],
)
def test_ch1_a_step_needs_a_fanout_before_it(step: Step) -> None:
    name = type(step).__name__
    with pytest.raises(ValueError, match=rf"^sf\.{name} needs a sf\.Fanout before it$"):
        sx.Pipeline([step])
    with pytest.raises(ValueError, match=rf"^sf\.{name} needs a sf\.Fanout before it$"):
        _ = sf.Model("provider/x") >> step
    with pytest.raises(ValueError, match=rf"^sf\.{name} needs a sf\.Fanout before it$"):
        _ = _block() >> step


def test_ch1_a_right_group_that_is_not_a_chain_alone_raises_when_it_is_built() -> None:
    with pytest.raises(ValueError, match=r"^sf\.Vote needs a sf\.Fanout before it$"):
        _ = sx.Fanout(_PAIR) >> (sx.Vote() >> sx.Vote())


# ---------------------------------------------------------------- CH-2


@pytest.mark.parametrize(
    "following",
    [
        sf.Model("provider/x"),
        "provider/x",
        sx.Fanout(_TRIO),
        _block(),
        sf.Fusion(_PAIR, synthesizer="provider/s"),
        sx.Pipeline(["provider/x", "provider/y"], name="named"),
    ],
    ids=["model", "route", "fanout", "closed-block", "old-fusion", "named-pipeline"],
)
def test_ch2_an_open_block_needs_a_terminal_before_the_next_stage(
    following: str | sf.Recipe | Step,
) -> None:
    with pytest.raises(ValueError, match=f"^{_CH2}$"):
        _ = sx.Fanout(_PAIR) >> following


def test_ch2_in_the_explicit_form() -> None:
    with pytest.raises(ValueError, match=f"^{_CH2}$"):
        sx.Pipeline([sx.Fanout(_PAIR), "provider/x", sx.Vote()])


# ---------------------------------------------------------------- CH-8


def test_ch8_an_open_chain_is_a_valid_value() -> None:
    chain = "provider/x" >> sx.Fanout(_PAIR)

    assert chain.steps == (sf.Model("provider/x"), sx.Fanout(_PAIR))
    assert chain >> sx.Vote() == sx.Pipeline(["provider/x", sx.Fanout(_PAIR), sx.Vote()])


def test_ch8_lowering_refuses_an_open_chain() -> None:
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        lower(sx.Pipeline(["provider/x", sx.Fanout(_PAIR)]))


def test_ch8_compile_refuses_an_open_chain_before_any_spend() -> None:
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        compile_candidate(sx.Pipeline(["provider/x", sx.Fanout(_PAIR)]))


def test_ch8_the_evaluation_entry_refuses_an_open_chain() -> None:
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        _candidate_values(sx.Pipeline(["provider/x", sx.Fanout(_PAIR)]))


def test_ch8_a_bare_fanout_is_not_a_recipe() -> None:
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        _candidate_values(sx.Fanout(_PAIR))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        sx.Fanout([sx.Fanout(_PAIR), "provider/c"])  # type: ignore[list-item]


def test_ch8_an_open_chain_is_not_a_member() -> None:
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        sx.Fanout([sx.Pipeline(["provider/x", sx.Fanout(_PAIR)]), "provider/c"])


# ---------------------------------------------------------------- CH-9


def test_ch9_the_fusion_rules_run_at_the_rshift_that_closes_the_block() -> None:
    fanout = sx.Fanout(_PAIR)
    vote = sx.Vote(weights=(1, 2, 3))

    with pytest.raises(ValueError, match="vote has 3 weights for 2 members"):
        _ = fanout >> vote


def test_ch9_an_undeclared_signal_raises_at_block_close() -> None:
    fanout = sx.Fanout(_PAIR, signals={"conf": sf.Verbalized("C: ([0-9]+)")})

    with pytest.raises(ValueError, match=r"reads sf\.signal\('other'\)"):
        _ = fanout >> sx.Vote(weights="other")


def test_ch9_a_logprob_member_rule_raises_at_block_close() -> None:
    fanout = sx.Fanout(_PAIR, signals={"p": sf.Logprob("prob")})

    with pytest.raises(ValueError, match="supports OpenRouter models in v1"):
        _ = fanout >> sx.Vote(weights="p")


def test_ch9_a_declared_signal_compiles_when_it_is_read() -> None:
    fanout = sx.Fanout(_PAIR, signals={"conf": sf.Verbalized("C: ([0-9]+)")})

    assert lower(fanout >> sx.Vote(weights="conf")) == sf.Fusion(
        _PAIR,
        signals={"conf": sf.Verbalized("C: ([0-9]+)")},
        synthesizer=sf.Vote(weights=sf.signal("conf")),
    )


# ---------------------------------------------------------------- CH-10 (no sf.Judge in the block)


def test_ch10_a_score_judge_read_with_no_judge_is_refused_at_block_close() -> None:
    vote = sx.Vote(weights="score:judge")

    with pytest.raises(
        ValueError, match=r"^score:judge needs sf\.Judge\(\.\.\.\) after sf\.Fanout$"
    ):
        _ = sx.Fanout(_PAIR) >> vote


# ---------------------------------------------------------------- CH-11


_STEPS = [sx.Vote(), sx.Median(), sx.Mean(), sx.Synthesize("provider/w")]
_STEP_IDS = ["vote", "median", "mean", "synthesize"]


def _step_message(step: Step) -> str:
    return rf"^sf\.{type(step).__name__} is a step, not a recipe: put it after a sf\.Fanout$"


@pytest.mark.parametrize("step", _STEPS, ids=_STEP_IDS)
def test_ch11_a_step_is_not_a_fanout_member(step: Step) -> None:
    with pytest.raises(TypeError, match=_step_message(step)):
        sx.Fanout(["provider/a", step])  # type: ignore[list-item]


@pytest.mark.parametrize("step", _STEPS, ids=_STEP_IDS)
def test_ch11_a_step_is_not_a_corrective_loop_member_or_judge(step: Step) -> None:
    with pytest.raises(TypeError, match=_step_message(step)):
        sf.CorrectiveLoop(["provider/a", step], judge="provider/j")  # type: ignore[list-item]
    with pytest.raises(TypeError, match=_step_message(step)):
        sf.CorrectiveLoop(["provider/a", "provider/b"], judge=step)  # type: ignore[arg-type]


@pytest.mark.parametrize("step", _STEPS, ids=_STEP_IDS)
def test_ch11_a_step_is_not_a_synthesize_model(step: Step) -> None:
    with pytest.raises(TypeError, match=_step_message(step)):
        sx.Synthesize(step)  # type: ignore[arg-type]


@pytest.mark.parametrize("step", _STEPS, ids=_STEP_IDS)
def test_ch11_a_step_is_not_a_candidate(step: Step) -> None:
    with pytest.raises(TypeError, match=_step_message(step)):
        _candidate_values(step)  # type: ignore[arg-type]


def test_a_closed_chain_is_a_corrective_loop_member() -> None:
    loop = sf.CorrectiveLoop([_block(), "provider/c"], judge="provider/j")

    assert lower(loop) == sf.CorrectiveLoop(
        [sf.Fusion(_PAIR, synthesizer=sf.Vote()), "provider/c"], judge="provider/j"
    )


# ---------------------------------------------------------------- CH-13

_LOOP = sf.CorrectiveLoop(["provider/a", "provider/b"], judge="provider/j")
_SOLO = sf.SelfCorrective("provider/a")


@pytest.mark.parametrize("root", [_LOOP, _SOLO], ids=["corrective-loop", "self-corrective"])
def test_ch13_a_corrective_root_is_not_a_chain_stage(root: sf.Recipe) -> None:
    message = r"^Pipeline stage must be a model route or sf\.Model, sf\.Fusion, or sf\.Pipeline$"
    with pytest.raises(TypeError, match=message):
        sx.Pipeline(["provider/x", root])
    with pytest.raises(TypeError, match=message):
        _ = _block() >> root


@pytest.mark.parametrize("root", [_LOOP, _SOLO], ids=["corrective-loop", "self-corrective"])
def test_ch13_a_corrective_root_is_not_a_fanout_member(root: sf.Recipe) -> None:
    message = r"^Fanout member must be a model route or sf\.Model, sf\.Fusion, or sf\.Pipeline$"
    with pytest.raises(TypeError, match=message):
        sx.Fanout(["provider/a", root])


# ---------------------------------------------------------------- CH-14


def test_ch14_a_named_pipeline_must_not_end_in_an_open_block() -> None:
    message = r"^a named sf\.Pipeline groups its stages, so close the sf\.Fanout block inside it$"
    with pytest.raises(ValueError, match=message):
        sx.Pipeline(["provider/x", sx.Fanout(_PAIR)], name="group")


def test_ch14_a_named_closed_pipeline_is_valid() -> None:
    chain = sx.Pipeline([sx.Fanout(_PAIR), sx.Vote()], name="group")

    assert chain.name == "group"
    assert lower(chain) == sf.Pipeline([sf.Fusion(_PAIR, synthesizer=sf.Vote())], name="group")
