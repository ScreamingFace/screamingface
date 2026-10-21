"""The chain rules of the map → select → reduce surface (E4b surface unit 2, surface §2).

FEATURE: ``a >> b`` builds one chain, read left to right. A ``sf.Fanout`` opens a block; a
reducer or ``sf.Synthesize`` closes it. Each refusal has its rule id (``CH-n``) and its message,
and raises at construction or at the ``>>`` that closes the block, never after a model call.
STORY: as a researcher, I write ``sf.Fanout(models) >> sf.Vote()`` and a wrong order fails at once
with a message that says what to do.
"""

from __future__ import annotations

import pytest
from _nodes import VoteNode, fusion_node

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import _candidate_values
from screamingface._surface.chain import Step, _Block
from screamingface._surface.lowering import lower

_PAIR = ["provider/a", "provider/b"]
_TRIO = ["provider/a", "provider/b", "provider/c"]
_OPEN = "the chain ends inside a sf.Fanout block: add a reducer or sf.Synthesize"
_CH2 = "a sf.Fanout block needs a reducer or sf.Synthesize before the next stage"


def _block() -> sf.Pipeline:
    return sf.Fanout(_PAIR) >> sf.Vote()


# ---------------------------------------------------------------- >> and sf.Pipeline


def test_rshift_builds_the_explicit_pipeline() -> None:
    assert sf.Fanout(_PAIR) >> sf.Vote() == sf.Pipeline([sf.Fanout(_PAIR), sf.Vote()])


def test_rshift_is_read_left_to_right() -> None:
    chain = sf.Fanout(_PAIR) >> sf.Vote() >> sf.Model("provider/after")

    assert chain == sf.Pipeline([sf.Fanout(_PAIR), sf.Vote(), sf.Model("provider/after")])
    assert chain.steps == (sf.Fanout(_PAIR), sf.Vote(), sf.Model("provider/after"))


def test_a_route_string_on_the_left_works_through_rrshift() -> None:
    chain = "provider/first" >> sf.Fanout(_PAIR) >> sf.Vote()

    assert chain == sf.Pipeline([sf.Model("provider/first"), sf.Fanout(_PAIR), sf.Vote()])


def test_a_model_on_the_left_works_through_rrshift() -> None:
    chain = sf.Model("provider/first") >> _block()

    assert chain == sf.Pipeline(["provider/first", sf.Fanout(_PAIR), sf.Vote()])


def test_an_unnamed_nested_pipeline_is_flattened() -> None:
    nested = sf.Pipeline([sf.Pipeline(["provider/x", sf.Fanout(_PAIR)]), sf.Vote()])

    assert nested == sf.Pipeline(["provider/x", sf.Fanout(_PAIR), sf.Vote()])
    assert lower(nested) == lower(sf.Pipeline(["provider/x", sf.Fanout(_PAIR), sf.Vote()]))


def test_a_named_nested_pipeline_keeps_its_grouping() -> None:
    group = sf.Pipeline(["provider/x", sf.Fanout(_PAIR), sf.Vote()], name="group")
    chain = group >> sf.Model("provider/after")

    assert chain.steps == (group, sf.Model("provider/after"))
    assert lower(chain) == sf.Pipeline(
        [
            sf.Pipeline(
                ["provider/x", fusion_node(_PAIR, VoteNode())],
                name="group",
            ),
            "provider/after",
        ]
    )


def test_an_unnamed_pipeline_of_today_is_flattened_as_an_unnamed_chain() -> None:
    today = sf.Pipeline(["provider/x", "provider/y"])

    assert sf.Pipeline([today, "provider/z"]) == sf.Pipeline(
        [sf.Pipeline(["provider/x", "provider/y"]), "provider/z"]
    )
    assert sf.Pipeline([today, "provider/z"]).steps == (
        sf.Model("provider/x"),
        sf.Model("provider/y"),
        sf.Model("provider/z"),
    )


def test_a_named_pipeline_of_today_keeps_its_grouping() -> None:
    today = sf.Pipeline(["provider/x", "provider/y"], name="group")

    assert sf.Pipeline([today, "provider/z"]).steps == (today, sf.Model("provider/z"))


def test_an_optional_unnamed_pipeline_of_today_is_not_a_stage() -> None:
    today = sf.Pipeline(["provider/x", "provider/y"], optional=True)

    with pytest.raises(ValueError, match="optional=True is only supported on sf.Fanout members"):
        sf.Pipeline([today, "provider/z"])


def test_the_chain_repr_does_not_show_private_fields() -> None:
    text = repr(sf.Pipeline([sf.Fanout(_PAIR), sf.Vote()], name="group"))

    assert "_is_named" not in text
    assert "_stages" not in text


def test_a_closed_block_is_recorded_as_a_block() -> None:
    chain = "provider/x" >> _block()

    (model, block) = chain._stages
    assert model == sf.Model("provider/x")
    assert isinstance(block, _Block)
    assert block.fanout == sf.Fanout(_PAIR)
    assert block.judge is None
    assert block.narrow == ()
    assert block.terminal == sf.Vote()
    assert block.node == fusion_node(_PAIR, VoteNode())


def test_an_empty_pipeline_is_refused() -> None:
    with pytest.raises(ValueError, match="a Pipeline requires at least one stage"):
        sf.Pipeline([])


def test_the_steps_must_be_a_sequence() -> None:
    with pytest.raises(TypeError, match="Pipeline stages must be an ordered sequence"):
        sf.Pipeline("provider/x")  # type: ignore[arg-type]


def test_an_optional_unnamed_chain_is_not_a_stage() -> None:
    optional = sf.Pipeline([sf.Fanout(_PAIR), sf.Vote()], optional=True)

    with pytest.raises(ValueError, match="optional=True is only supported on sf.Fanout members"):
        _ = optional >> sf.Model("provider/after")


# ---------------------------------------------------------------- CH-1


@pytest.mark.parametrize(
    "step",
    [sf.Vote(), sf.Median(), sf.Mean(), sf.Synthesize("provider/w")],
    ids=["vote", "median", "mean", "synthesize"],
)
def test_ch1_a_step_needs_a_fanout_before_it(step: Step) -> None:
    name = type(step).__name__
    with pytest.raises(ValueError, match=rf"^sf\.{name} needs a sf\.Fanout before it$"):
        sf.Pipeline([step])
    with pytest.raises(ValueError, match=rf"^sf\.{name} needs a sf\.Fanout before it$"):
        _ = sf.Model("provider/x") >> step
    with pytest.raises(ValueError, match=rf"^sf\.{name} needs a sf\.Fanout before it$"):
        _ = _block() >> step


def test_ch1_a_right_group_that_is_not_a_chain_alone_raises_when_it_is_built() -> None:
    with pytest.raises(ValueError, match=r"^sf\.Vote needs a sf\.Fanout before it$"):
        _ = sf.Fanout(_PAIR) >> (sf.Vote() >> sf.Vote())


# ---------------------------------------------------------------- CH-2


@pytest.mark.parametrize(
    "following",
    [
        sf.Model("provider/x"),
        "provider/x",
        sf.Fanout(_TRIO),
        _block(),
        fusion_node(_PAIR, "provider/s"),
        sf.Pipeline(["provider/x", "provider/y"], name="named"),
    ],
    ids=["model", "route", "fanout", "closed-block", "old-fusion", "named-pipeline"],
)
def test_ch2_an_open_block_needs_a_terminal_before_the_next_stage(
    following: str | sf.Recipe | Step,
) -> None:
    with pytest.raises(ValueError, match=f"^{_CH2}$"):
        _ = sf.Fanout(_PAIR) >> following


def test_ch2_in_the_explicit_form() -> None:
    with pytest.raises(ValueError, match=f"^{_CH2}$"):
        sf.Pipeline([sf.Fanout(_PAIR), "provider/x", sf.Vote()])


# ---------------------------------------------------------------- CH-8


def test_ch8_an_open_chain_is_a_valid_value() -> None:
    chain = "provider/x" >> sf.Fanout(_PAIR)

    assert chain.steps == (sf.Model("provider/x"), sf.Fanout(_PAIR))
    assert chain >> sf.Vote() == sf.Pipeline(["provider/x", sf.Fanout(_PAIR), sf.Vote()])


def test_ch8_lowering_refuses_an_open_chain() -> None:
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        lower(sf.Pipeline(["provider/x", sf.Fanout(_PAIR)]))


def test_ch8_compile_refuses_an_open_chain_before_any_spend() -> None:
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        compile_candidate(sf.Pipeline(["provider/x", sf.Fanout(_PAIR)]))


def test_ch8_the_evaluation_entry_refuses_an_open_chain() -> None:
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        _candidate_values(sf.Pipeline(["provider/x", sf.Fanout(_PAIR)]))


def test_ch8_a_bare_fanout_is_not_a_recipe() -> None:
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        _candidate_values(sf.Fanout(_PAIR))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        sf.Fanout([sf.Fanout(_PAIR), "provider/c"])  # type: ignore[list-item]


def test_ch8_an_open_chain_is_not_a_member() -> None:
    with pytest.raises(ValueError, match=f"^{_OPEN}$"):
        sf.Fanout([sf.Pipeline(["provider/x", sf.Fanout(_PAIR)]), "provider/c"])


# ---------------------------------------------------------------- CH-9


def test_ch9_the_fusion_rules_run_at_the_rshift_that_closes_the_block() -> None:
    fanout = sf.Fanout(_PAIR)
    vote = sf.Vote(weights=(1, 2, 3))

    with pytest.raises(ValueError, match="vote has 3 weights for 2 members"):
        _ = fanout >> vote


def test_ch9_an_undeclared_signal_raises_at_block_close() -> None:
    fanout = sf.Fanout(_PAIR, signals={"conf": sf.Verbalized("C: ([0-9]+)")})

    with pytest.raises(ValueError, match=r"reads sf\.signal\('other'\)"):
        _ = fanout >> sf.Vote(weights="other")


def test_ch9_a_logprob_member_rule_raises_at_block_close() -> None:
    fanout = sf.Fanout(_PAIR, signals={"p": sf.Logprob("prob")})

    with pytest.raises(ValueError, match="supports OpenRouter models in v1"):
        _ = fanout >> sf.Vote(weights="p")


def test_ch9_a_declared_signal_compiles_when_it_is_read() -> None:
    fanout = sf.Fanout(_PAIR, signals={"conf": sf.Verbalized("C: ([0-9]+)")})

    assert lower(fanout >> sf.Vote(weights="conf")) == fusion_node(
        _PAIR,
        signals={"conf": sf.Verbalized("C: ([0-9]+)")},
        reducer=VoteNode(weights=sf.signal("conf")),
    )


# ---------------------------------------------------------------- CH-10 (no sf.Judge in the block)


def test_ch10_a_score_judge_read_with_no_judge_is_refused_at_block_close() -> None:
    vote = sf.Vote(weights="score:judge")

    with pytest.raises(
        ValueError, match=r"^score:judge needs sf\.Judge\(\.\.\.\) after sf\.Fanout$"
    ):
        _ = sf.Fanout(_PAIR) >> vote


# ---------------------------------------------------------------- CH-11


_STEPS = [sf.Vote(), sf.Median(), sf.Mean(), sf.Synthesize("provider/w")]
_STEP_IDS = ["vote", "median", "mean", "synthesize"]


def _step_message(step: Step) -> str:
    return rf"^sf\.{type(step).__name__} is a step, not a recipe: put it after a sf\.Fanout$"


@pytest.mark.parametrize("step", _STEPS, ids=_STEP_IDS)
def test_ch11_a_step_is_not_a_fanout_member(step: Step) -> None:
    with pytest.raises(TypeError, match=_step_message(step)):
        sf.Fanout(["provider/a", step])  # type: ignore[list-item]


@pytest.mark.parametrize("step", _STEPS, ids=_STEP_IDS)
def test_ch11_a_step_is_not_a_corrective_loop_member_or_judge(step: Step) -> None:
    with pytest.raises(TypeError, match=_step_message(step)):
        sf.CorrectiveLoop(["provider/a", step], judge="provider/j")  # type: ignore[list-item]
    with pytest.raises(TypeError, match=_step_message(step)):
        sf.CorrectiveLoop(["provider/a", "provider/b"], judge=step)  # type: ignore[arg-type]


@pytest.mark.parametrize("step", _STEPS, ids=_STEP_IDS)
def test_ch11_a_step_is_not_a_synthesize_model(step: Step) -> None:
    with pytest.raises(TypeError, match=_step_message(step)):
        sf.Synthesize(step)  # type: ignore[arg-type]


@pytest.mark.parametrize("step", _STEPS, ids=_STEP_IDS)
def test_ch11_a_step_is_not_a_candidate(step: Step) -> None:
    with pytest.raises(TypeError, match=_step_message(step)):
        _candidate_values(step)  # type: ignore[arg-type]


def test_a_closed_chain_is_a_corrective_loop_member() -> None:
    loop = sf.CorrectiveLoop([_block(), "provider/c"], judge="provider/j")

    assert lower(loop) == sf.CorrectiveLoop(
        [fusion_node(_PAIR, VoteNode()), "provider/c"], judge="provider/j"
    )


# ---------------------------------------------------------------- CH-13

_LOOP = sf.CorrectiveLoop(["provider/a", "provider/b"], judge="provider/j")
_SOLO = sf.SelfCorrective("provider/a")


@pytest.mark.parametrize("root", [_LOOP, _SOLO], ids=["corrective-loop", "self-corrective"])
def test_ch13_a_corrective_root_is_not_a_chain_stage(root: sf.Recipe) -> None:
    message = r"^Pipeline stage must be a model route, an sf\.Model or an sf\.Pipeline$"
    with pytest.raises(TypeError, match=message):
        sf.Pipeline(["provider/x", root])
    with pytest.raises(TypeError, match=message):
        _ = _block() >> root


@pytest.mark.parametrize("root", [_LOOP, _SOLO], ids=["corrective-loop", "self-corrective"])
def test_ch13_a_corrective_root_is_not_a_fanout_member(root: sf.Recipe) -> None:
    message = r"^Fanout member must be a model route, an sf\.Model or an sf\.Pipeline$"
    with pytest.raises(TypeError, match=message):
        sf.Fanout(["provider/a", root])


# ---------------------------------------------------------------- CH-14


def test_ch14_a_named_pipeline_must_not_end_in_an_open_block() -> None:
    message = r"^a named sf\.Pipeline groups its stages, so close the sf\.Fanout block inside it$"
    with pytest.raises(ValueError, match=message):
        sf.Pipeline(["provider/x", sf.Fanout(_PAIR)], name="group")


def test_ch14_a_named_closed_pipeline_is_valid() -> None:
    chain = sf.Pipeline([sf.Fanout(_PAIR), sf.Vote()], name="group")

    assert chain.name == "group"
    assert lower(chain) == sf.Pipeline([fusion_node(_PAIR, VoteNode())], name="group")
