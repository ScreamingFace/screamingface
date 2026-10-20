"""``sf.Synthesize``: the write step of a block (E4b surface unit 2, surface §8, D6).

FEATURE: ``sf.Synthesize(model, *, prompt=None)`` closes a block with a model that writes the
answer. ``prompt=`` is the writer prompt; it is refused when the model already has one, or when
the model is a recipe that is not a ``sf.Model`` (SY-1).
STORY: as a researcher, I name the writer and its prompt in one step after the panel.
"""

from __future__ import annotations

import inspect

import pytest
from screamingface._surface.lowering import lower

import screamingface as sf
from screamingface import _surface as sx

_PAIR = ["provider/a", "provider/b"]
_PROMPT = "Write the final answer from the drafts."


def _written(writer: sx.Synthesize) -> sf.Recipe:
    node = lower(sx.Fanout(_PAIR) >> writer)
    assert isinstance(node, sf.Fusion)
    synthesizer = node.synthesizer
    assert isinstance(synthesizer, sf.Recipe)
    return synthesizer


def test_a_route_is_a_model_with_the_default_prompt() -> None:
    assert _written(sx.Synthesize("provider/w")) == sf.Model("provider/w")


def test_a_route_with_a_prompt_is_a_model_with_that_prompt() -> None:
    assert _written(sx.Synthesize("provider/w", prompt=_PROMPT)) == sf.Model(
        "provider/w", prompt=_PROMPT
    )


def test_a_model_with_no_prompt_takes_the_prompt_and_keeps_the_rest() -> None:
    model = sf.Model("provider/w", name="writer", params={"temperature": 0})

    assert _written(sx.Synthesize(model, prompt=_PROMPT)) == sf.Model(
        "provider/w", name="writer", prompt=_PROMPT, params={"temperature": 0}
    )


def test_a_model_with_its_own_prompt_stays_as_it_is() -> None:
    model = sf.Model("provider/w", prompt=_PROMPT)

    assert _written(sx.Synthesize(model)) is model


def test_a_recipe_writer_lowers_to_its_lowered_value() -> None:
    inner = sx.Pipeline(["provider/j", "provider/w"], name="judge-write")

    assert _written(sx.Synthesize(inner)) == sf.Pipeline(
        ["provider/j", "provider/w"], name="judge-write"
    )


def test_a_closed_chain_writer_lowers_to_its_node() -> None:
    inner = sx.Fanout(["provider/x", "provider/y"]) >> sx.Synthesize("provider/s")

    assert _written(sx.Synthesize(inner)) == sf.Fusion(
        ["provider/x", "provider/y"], synthesizer="provider/s"
    )


def test_sy1_a_prompt_on_a_model_that_has_one_is_refused() -> None:
    message = r"^sf\.Synthesize prompt= sets the writer prompt: the sf\.Model already has one$"
    with pytest.raises(ValueError, match=message):
        sx.Synthesize(sf.Model("provider/w", prompt="Mine."), prompt=_PROMPT)


@pytest.mark.parametrize(
    "recipe",
    [
        sf.Pipeline(["provider/j", "provider/w"]),
        sx.Fanout(_PAIR) >> sx.Vote(),
        sf.Fusion(_PAIR, synthesizer="provider/s"),
    ],
    ids=["pipeline", "chain", "fusion"],
)
def test_sy1_a_prompt_on_a_recipe_writer_is_refused(recipe: sf.Recipe) -> None:
    message = (
        r"^sf\.Synthesize prompt= needs a model route or a sf\.Model: "
        r"a recipe writer uses its own prompts$"
    )
    with pytest.raises(ValueError, match=message):
        sx.Synthesize(recipe, prompt=_PROMPT)


def test_sy1_a_blank_prompt_is_refused() -> None:
    with pytest.raises(ValueError, match="synthesize prompt must not be empty"):
        sx.Synthesize("provider/w", prompt=" ")


def test_an_optional_writer_is_refused() -> None:
    with pytest.raises(ValueError, match="optional=True is only supported on Fusion members"):
        sx.Synthesize(sf.Model("provider/w", optional=True))


def test_the_docstring_names_the_three_input_forms() -> None:
    doc = inspect.getdoc(sx.Synthesize)

    assert doc is not None
    assert "outputs" in doc and "panel" in doc  # right after sf.Fanout: the Fusion context
    assert '"selected"' in doc  # after sf.Rank or sf.Filter: the selection envelope
    assert "sf.Concat" in doc  # after sf.Concat: the joined text
