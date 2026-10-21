from __future__ import annotations

from typing import Any, cast

import pytest

import screamingface as sf


def test_pipeline_is_an_immutable_ordered_recipe() -> None:
    draft = sf.Model("provider/draft")
    review = sf.Model("provider/review")

    pipeline = sf.Pipeline([draft, review], name=" Review chain ")

    assert isinstance(pipeline, sf.Recipe)
    assert pipeline.name == "Review chain"
    assert pipeline.stages == (draft, review)
    assert pipeline.stages[0] is draft
    assert pipeline.stages[1] is review

    with pytest.raises(AttributeError):
        cast(Any, pipeline).stages = ()


def test_pipeline_accepts_one_stage_and_route_shorthand() -> None:
    one = sf.Pipeline(["provider/only"])
    mixed = sf.Pipeline([sf.Model("provider/a"), "provider/b"])

    assert one.stages == (sf.Model("provider/only"),)
    assert mixed.stages == (sf.Model("provider/a"), sf.Model("provider/b"))


def test_pipeline_rejects_empty_or_ambiguous_stage_collections() -> None:
    with pytest.raises(ValueError, match="at least one stage"):
        sf.Pipeline([])

    with pytest.raises(TypeError, match="ordered sequence"):
        sf.Pipeline(cast(Any, "provider/a"))


def test_then_builds_the_same_canonical_ordered_pipeline() -> None:
    draft = sf.Model("provider/draft")
    review = sf.Model("provider/review")
    final = sf.Model("provider/final")

    pair = draft >> review
    trio = pair >> final

    assert isinstance(pair, sf.Pipeline)
    assert pair.steps == (draft, review)
    assert trio.steps == (draft, review, final)
    assert pair.steps == (draft, review)
    assert trio.name == "draft->review->final"


def test_pipeline_infers_a_compact_serial_name_and_representation() -> None:
    pipeline = sf.Pipeline(
        [sf.Model("provider/draft"), sf.Model("provider/review")],
    )

    assert pipeline.name == "draft->review"
    assert repr(pipeline) == "Pipeline(['draft', 'review'])"
    assert repr(sf.Pipeline(pipeline.stages, name="review chain")) == (
        "Pipeline(['draft', 'review'], name='review chain')"
    )


def test_then_preserves_an_explicitly_named_pipeline_as_one_stage() -> None:
    named = sf.Pipeline(
        [sf.Model("provider/draft"), sf.Model("provider/review")],
        name="review-chain",
    )
    final = sf.Model("provider/final")

    pipeline = named >> final

    assert pipeline.steps == (named, final)
    assert pipeline.name == "review-chain->final"


def test_unnamed_nested_pipelines_flatten_to_one_canonical_stage_sequence() -> None:
    draft = sf.Model("provider/draft")
    review = sf.Model("provider/review")
    final = sf.Model("provider/final")

    constructed = sf.Pipeline([draft, sf.Pipeline([review, final])])
    chained = draft >> sf.Pipeline([review, final])

    assert constructed.stages == (draft, review, final)
    assert chained.steps == (draft, review, final)


def test_fusion_accepts_pipelines_as_members_and_complete_recipe_synthesizers() -> None:
    pipeline_member = sf.Pipeline(
        [sf.Model("provider/draft"), sf.Model("provider/review")],
        name="review-chain",
    )
    pipeline_synthesizer = sf.Pipeline(
        [sf.Model("provider/judge"), sf.Model("provider/writer")],
        name="judge-and-write",
    )
    nested_fusion_synthesizer = sf.Fanout(
        [sf.Model("provider/editor-a"), sf.Model("provider/editor-b")]
    ) >> sf.Synthesize("provider/final-editor")

    with_pipeline = sf.Fanout([pipeline_member, sf.Model("provider/alternative")]) >> sf.Synthesize(
        pipeline_synthesizer
    )
    with_nested_fusion = sf.Fanout(
        [sf.Model("provider/a"), sf.Model("provider/b")]
    ) >> sf.Synthesize(nested_fusion_synthesizer)

    fanout, writer = with_pipeline.steps
    nested_writer = with_nested_fusion.steps[1]
    assert isinstance(fanout, sf.Fanout)
    assert isinstance(writer, sf.Synthesize)
    assert isinstance(nested_writer, sf.Synthesize)
    assert fanout.members[0] is pipeline_member
    assert writer.model is pipeline_synthesizer
    assert nested_writer.model is nested_fusion_synthesizer


def test_then_accepts_any_complete_recipe_or_route_and_rejects_a_list() -> None:
    fusion = sf.Fanout([sf.Model("provider/a"), sf.Model("provider/b")]) >> sf.Synthesize(
        "provider/synth"
    )
    pipeline = sf.Model("provider/draft") >> fusion

    # WHY steps[1:]: an unnamed chain stage is flattened into the chain, step by step.
    assert pipeline.steps[1:] == fusion.steps
    assert (sf.Model("provider/draft") >> "provider/final").steps == (
        sf.Model("provider/draft"),
        sf.Model("provider/final"),
    )

    with pytest.raises(TypeError, match="Pipeline stage must be"):
        _ = sf.Model("provider/draft") >> cast(Any, [sf.Model("provider/final")])


def test_recipe_values_have_structural_equality_and_are_unhashable() -> None:
    left = sf.Pipeline(
        [
            "provider/draft",
            sf.Fanout(["provider/a"]) >> sf.Synthesize("provider/synth"),
        ],
        name="candidate",
    )
    right = sf.Pipeline(
        [
            sf.Model("provider/draft"),
            sf.Fanout([sf.Model("provider/a")]) >> sf.Synthesize(sf.Model("provider/synth")),
        ],
        name="candidate",
    )

    assert left == right
    with pytest.raises(TypeError, match="unhashable"):
        hash(left)


def test_explicit_naming_is_visible_even_when_it_matches_the_inferred_name() -> None:
    unnamed = sf.Pipeline(["provider/a", "provider/b"])
    named = sf.Pipeline(["provider/a", "provider/b"], name="a->b")

    # WHY: the spec keeps an explicitly named nested Pipeline grouped instead of
    # flattening it, so namedness is behavioral — equality AND repr must show it.
    assert named != unnamed
    assert repr(unnamed) == "Pipeline(['a', 'b'])"
    assert repr(named) == "Pipeline(['a', 'b'], name='a->b')"
    assert sf.Pipeline([named, "provider/c"]).stages == (named, sf.Model("provider/c"))
    assert sf.Pipeline([unnamed, "provider/c"]).stages == (
        sf.Model("provider/a"),
        sf.Model("provider/b"),
        sf.Model("provider/c"),
    )
