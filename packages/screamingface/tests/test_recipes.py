from __future__ import annotations

import re
from types import MappingProxyType
from typing import Any, cast

import pytest
from _nodes import FusionNode

import screamingface as sf


def _block(chain: sf.Pipeline) -> tuple[sf.Fanout, sf.Synthesize]:
    """The two steps of a one-block chain: its Fanout and its writer."""
    fanout, writer = chain.steps
    assert isinstance(fanout, sf.Fanout)
    assert isinstance(writer, sf.Synthesize)
    return fanout, writer


def test_model_is_an_immutable_network_free_candidate() -> None:
    model = sf.Model("openrouter/anthropic/claude-opus-4.8")

    assert isinstance(model, sf.Recipe)
    assert model.model == "openrouter/anthropic/claude-opus-4.8"
    assert model.name == "claude-opus-4.8"
    assert not hasattr(model, "instructions")
    assert not hasattr(model, "temperature")
    assert not hasattr(model, "reasoning")
    assert not hasattr(model, "max_output_tokens")
    assert not hasattr(model, "url4")

    with pytest.raises(AttributeError):
        cast(Any, model).model = "provider/other"


def test_explicit_model_name_is_a_trimmed_sample_identity() -> None:
    model = sf.Model(
        "openrouter/anthropic/claude-opus-4.8",
        name=" Opus Sample 1 ",
    )

    assert model.name == "Opus Sample 1"
    assert model._sample_id == "Opus Sample 1"


def test_model_accepts_optional_candidate_owned_prompt_and_parameters() -> None:
    model = sf.Model(
        "provider/model",
        prompt="Answer using primary evidence.",
        params={"temperature": 0.4, "reasoning": "high"},
    )

    assert model.prompt == "Answer using primary evidence."
    assert model.params == {"temperature": 0.4, "reasoning": "high"}
    assert isinstance(model.params, MappingProxyType)


@pytest.mark.parametrize(
    "params",
    [
        {"stop": ")("},
        {"stop": "'"},
        {"bad&name": "value"},
    ],
)
def test_candidate_parameters_reject_values_that_cannot_be_encoded(
    params: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="cannot be encoded"):
        sf.Model("provider/model", params=params)

    with pytest.raises(ValueError, match="cannot be encoded"):
        _ = sf.Fanout([sf.Model("provider/a"), sf.Model("provider/b")]) >> sf.Synthesize(
            sf.Model("provider/synth", params=params)
        )


def test_fusion_keeps_members_in_order_and_infers_a_name() -> None:
    opus = sf.Model("openrouter/anthropic/claude-opus-4.8")
    gpt = sf.Model("openrouter/openai/gpt-5.5")

    synthesizer = sf.Model("openrouter/openai/gpt-5.5")
    fusion = sf.Fanout([opus, gpt]) >> sf.Synthesize(synthesizer)
    fanout, writer = _block(fusion)

    assert isinstance(fusion, sf.Recipe)
    assert fusion.name == "claude-opus-4.8+gpt-5.5"
    assert fanout.members == (opus, gpt)
    assert fanout.members[0] is opus
    assert fanout.members[1] is gpt
    assert writer.model is synthesizer
    assert not hasattr(fusion, "reducer")
    assert not hasattr(fusion, "url4")


def test_fusion_accepts_an_optional_display_name() -> None:
    fusion = sf.Fanout(
        [sf.Model("provider/opus"), sf.Model("provider/gpt")], name=" Frontier "
    ) >> sf.Synthesize("provider/synth")

    assert fusion.name == "Frontier"


def test_fusion_accepts_a_model_with_candidate_owned_synthesis_policy() -> None:
    synthesizer = sf.Model(
        "provider/synth",
        prompt="Resolve disagreements using evidence.",
        params={"temperature": 0.1},
    )
    fusion = sf.Fanout([sf.Model("provider/a"), sf.Model("provider/b")]) >> sf.Synthesize(
        synthesizer
    )
    _, writer = _block(fusion)

    assert writer.model is synthesizer
    assert isinstance(writer.model, sf.Model)
    assert writer.model.prompt == "Resolve disagreements using evidence."
    assert writer.model.params == {"temperature": 0.1}


def test_fusion_normalizes_synthesizer_route_shorthand_to_a_model() -> None:
    fusion = sf.Fanout([sf.Model("provider/a"), sf.Model("provider/b")]) >> sf.Synthesize(
        "provider/synth"
    )
    _, writer = _block(fusion)

    assert isinstance(writer.model, sf.Model)
    assert writer.model.model == "provider/synth"


def test_fusion_requires_an_explicit_synthesizer() -> None:
    with pytest.raises(TypeError, match="required keyword-only argument: 'synthesizer'"):
        cast(Any, FusionNode)([sf.Model("provider/a"), sf.Model("provider/b")])

    fusion = sf.Fanout(["provider/a"]) >> sf.Synthesize("provider/synth")
    fanout, writer = _block(fusion)
    assert fanout.members == (sf.Model("provider/a"),)
    assert writer.model == sf.Model("provider/synth")
    assert not hasattr(fusion, "prompt")
    assert not hasattr(fusion, "params")


def test_nested_fusions_are_regular_members() -> None:
    opus = sf.Model("provider/opus")
    gpt = sf.Model("provider/gpt")
    gemini = sf.Model("provider/gemini")
    pair = sf.Fanout([opus, gpt], name="pair") >> sf.Synthesize("provider/pair-synth")
    trio = sf.Fanout([pair, gemini], name="trio") >> sf.Synthesize("provider/trio-synth")

    trio_fanout, _ = _block(trio)
    assert trio_fanout.members == (pair, gemini)
    nested, _ = _block(cast(sf.Pipeline, trio_fanout.members[0]))
    assert nested.members == (opus, gpt)


def test_explicit_names_distinguish_independent_samples() -> None:
    first = sf.Model("provider/opus", name="sample-1")
    second = sf.Model("provider/opus", name="sample-2")

    assert first is not second
    assert first != second

    fusion = sf.Fanout([first, second], name="self-fusion") >> sf.Synthesize("provider/synth")
    fanout, _ = _block(fusion)
    assert fanout.members == (first, second)


def test_fusion_accepts_one_member_routes_and_duplicate_display_names() -> None:
    fusion = sf.Fanout(
        ["provider/one", sf.Model("provider-a/same"), sf.Model("provider-b/same")]
    ) >> sf.Synthesize("provider/synth")
    fanout, _ = _block(fusion)

    assert fanout.members == (
        sf.Model("provider/one"),
        sf.Model("provider-a/same"),
        sf.Model("provider-b/same"),
    )


def test_fusion_rejects_empty_or_ambiguous_member_collections() -> None:
    with pytest.raises(ValueError, match="at least one member"):
        _ = sf.Fanout([]) >> sf.Synthesize("provider/synth")

    with pytest.raises(TypeError, match="ordered sequence"):
        _ = sf.Fanout(cast(Any, "provider/one")) >> sf.Synthesize("provider/synth")


def test_fusion_rejects_unpublished_recipe_extensions() -> None:
    class CustomRecipe(sf.Recipe):
        name = "custom"

        @property
        def _recipe_marker(self) -> None:
            return None

    with pytest.raises(TypeError, match="sf.Model, sf.Fusion, or sf.Pipeline"):
        _ = sf.Fanout([CustomRecipe(), sf.Model("provider/model")]) >> sf.Synthesize(
            "provider/synth"
        )


def test_fusion_rejects_unsupported_recipe_synthesizers() -> None:
    with pytest.raises(
        TypeError,
        match=re.escape(
            "Synthesize model must be a model route or sf.Model, sf.Fusion, or sf.Pipeline"
        ),
    ):
        _ = sf.Fanout([sf.Model("provider/a"), sf.Model("provider/b")]) >> sf.Synthesize(
            cast(Any, object())
        )


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: sf.Model("provider/model", name=" "), "model name"),
        (
            lambda: (
                sf.Fanout([sf.Model("provider/a"), sf.Model("provider/b")], name=" ")
                >> sf.Synthesize("provider/synth")
            ),
            "fanout name must not be empty",
        ),
    ],
)
def test_candidates_reject_invalid_names(factory: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        cast(Any, factory)()


@pytest.mark.parametrize(
    "keyword", ["instructions", "temperature", "reasoning", "max_output_tokens"]
)
def test_model_rejects_undeclared_generation_keywords(keyword: str) -> None:
    with pytest.raises(TypeError, match=f"unexpected keyword argument '{keyword}'"):
        cast(Any, sf.Model)("provider/model", **{keyword: object()})


def test_recipe_is_a_non_constructible_umbrella_type() -> None:
    with pytest.raises(TypeError, match="abstract"):
        cast(Any, sf.Recipe)()


def test_candidate_representations_are_compact() -> None:
    opus = sf.Model("openrouter/anthropic/claude-opus-4.8")
    sample = sf.Model(
        "openrouter/anthropic/claude-opus-4.8",
        name="sample-1",
    )
    gpt = sf.Model("openrouter/openai/gpt-5.5")

    assert repr(opus) == "Model('openrouter/anthropic/claude-opus-4.8')"
    assert repr(sample) == ("Model('openrouter/anthropic/claude-opus-4.8', name='sample-1')")
    assert repr(sf.Fanout([opus, gpt]) >> sf.Synthesize("provider/synth")) == (
        "Fanout(['openrouter/anthropic/claude-opus-4.8', 'openrouter/openai/gpt-5.5']) "
        ">> Synthesize('provider/synth')"
    )
    assert repr(sf.Fanout([opus, gpt], name="pair") >> sf.Synthesize("provider/synth")) == (
        "Fanout(['openrouter/anthropic/claude-opus-4.8', 'openrouter/openai/gpt-5.5'], "
        "name='pair') >> Synthesize('provider/synth')"
    )


def test_candidate_representations_include_behavioral_overrides() -> None:
    model = sf.Model(
        "provider/model",
        name="sample",
        prompt="Use evidence.",
        params={"temperature": 0.2},
    )
    fusion = sf.Fanout(
        [sf.Model("provider/a"), sf.Model("provider/b")], name="pair"
    ) >> sf.Synthesize(
        sf.Model(
            "provider/synth",
            prompt="Resolve conflicts.",
            params={"reasoning": "high"},
        )
    )

    assert repr(model) == (
        "Model('provider/model', name='sample', prompt='Use evidence.', "
        "params={'temperature': 0.2})"
    )
    assert repr(fusion) == (
        "Fanout(['provider/a', 'provider/b'], name='pair') >> "
        "Synthesize(Model('provider/synth', prompt='Resolve conflicts.', "
        "params={'reasoning': 'high'}))"
    )
