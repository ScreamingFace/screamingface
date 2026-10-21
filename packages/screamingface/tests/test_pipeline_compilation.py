from __future__ import annotations

import pytest
from url4 import Expression, RelExpr, Source, build

import screamingface as sf
from screamingface._evaluation.benchmark import _decode_benchmark_resource
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.compilation import compile_evaluation


def _whole_candidate_benchmark():
    return _decode_benchmark_resource(
        {
            "schema": "screamingface.benchmark.v1",
            "id": "fixture",
            "title": "Fixture",
            "description": "One whole-Candidate fixture.",
            "revision": "fixture-revision",
            "case_count": 1,
            "url4": "(answer:0.0:/candidate?q=(question)!'$candidate')!'$answer'",
        },
        requested_id="fixture",
        requested_limit=1,
    )


def test_pipeline_compiles_each_stage_against_the_previous_answer() -> None:
    pipeline = sf.Pipeline(
        [
            sf.Model("provider/draft", prompt="Draft an answer."),
            sf.Model("provider/review", prompt="Review the draft."),
            sf.Model("provider/final", prompt="Return the final answer."),
        ],
    )

    compiled = compile_candidate(pipeline)

    assert compiled.kind == "pipeline"
    assert compiled.models == ("provider/draft", "provider/review", "provider/final")
    assert compiled.url4 is not None
    expression = build(compiled.url4)
    assert isinstance(expression, Expression)
    calls = [
        source.value
        for source in expression.sources
        if isinstance(source, Source) and isinstance(source.value, RelExpr)
    ]
    assert [(call.path, call.context) for call in calls] == [
        ("/provider/draft", "$input"),
        ("/provider/review", "$model_1"),
        ("/provider/final", "$model_2"),
    ]
    assert [operation.kind for operation in compiled.operations] == ["model", "model", "model"]
    assert [operation.depends_on for operation in compiled.operations] == [
        (),
        ("op_model_1",),
        ("op_model_2",),
    ]


def test_pipeline_compiles_a_parallel_fusion_as_one_serial_stage() -> None:
    pipeline = sf.Pipeline(
        [
            sf.Model("provider/draft"),
            sf.Fanout([sf.Model("provider/reviewer-a"), sf.Model("provider/reviewer-b")])
            >> sf.Synthesize("provider/reconciler"),
            sf.Model("provider/final"),
        ]
    )

    compiled = compile_candidate(pipeline)

    assert compiled.kind == "pipeline"
    assert compiled.models == (
        "provider/draft",
        "provider/reviewer-a",
        "provider/reviewer-b",
        "provider/reconciler",
        "provider/final",
    )
    assert compiled.url4 is not None
    expression = build(compiled.url4)
    assert isinstance(expression, Expression)
    calls = [
        source.value
        for source in expression.sources
        if isinstance(source, Source) and isinstance(source.value, RelExpr)
    ]
    assert [(call.path, call.context) for call in calls[:3]] == [
        ("/provider/draft", "$input"),
        ("/provider/reviewer-a", "$model_1"),
        ("/provider/reviewer-b", "$model_1"),
    ]
    assert calls[3].path == "/provider/reconciler"
    assert "input: '$model_1'" in (calls[3].context or "")
    assert "outputs:" in (calls[3].context or "")
    assert "$model_2" in (calls[3].context or "")
    assert "$model_3" in (calls[3].context or "")
    assert (calls[4].path, calls[4].context) == ("/provider/final", "$synthesis_1")
    assert [operation.depends_on for operation in compiled.operations] == [
        (),
        ("op_model_1",),
        ("op_model_1",),
        ("op_model_2", "op_model_3"),
        ("op_synthesis_1",),
    ]


def test_fusion_compiles_pipeline_members_and_a_pipeline_synthesizer() -> None:
    member = sf.Pipeline(
        [sf.Model("provider/draft"), sf.Model("provider/review")],
        name="review-chain",
    )
    synthesizer = sf.Pipeline(
        [
            sf.Model("provider/judge", prompt="Select the strongest answer."),
            sf.Model("provider/writer", prompt="Polish the selected answer."),
        ],
        name="judge-and-write",
    )
    fusion = sf.Fanout([member, sf.Model("provider/alternative")]) >> sf.Synthesize(synthesizer)

    compiled = compile_candidate(fusion)

    assert compiled.kind == "fusion"
    assert compiled.models == (
        "provider/draft",
        "provider/review",
        "provider/alternative",
        "provider/judge",
        "provider/writer",
    )
    assert tuple(member.kind for member in compiled.members) == ("pipeline", "model")
    assert compiled.url4 is not None
    expression = build(compiled.url4)
    assert isinstance(expression, Expression)
    calls = [
        source.value
        for source in expression.sources
        if isinstance(source, Source) and isinstance(source.value, RelExpr)
    ]
    assert [(call.path, call.context) for call in calls[:3]] == [
        ("/provider/draft", "$input"),
        ("/provider/review", "$model_1"),
        ("/provider/alternative", "$input"),
    ]
    assert calls[3].path == "/provider/judge"
    assert "$model_2" in (calls[3].context or "")
    assert "$model_3" in (calls[3].context or "")
    assert (calls[4].path, calls[4].context) == ("/provider/writer", "$model_4")
    assert [operation.kind for operation in compiled.operations] == [
        "model",
        "model",
        "model",
        "synthesis",
        "model",
    ]
    assert [operation.depends_on for operation in compiled.operations] == [
        (),
        ("op_model_1",),
        (),
        ("op_model_2", "op_model_3"),
        ("op_model_4",),
    ]


def test_fusion_compiles_a_complete_fusion_as_its_synthesizer() -> None:
    synthesizer = sf.Fanout(
        [sf.Model("provider/editor-a"), sf.Model("provider/editor-b")]
    ) >> sf.Synthesize("provider/final-editor")

    compiled = compile_candidate(
        sf.Fanout([sf.Model("provider/proposer-a"), sf.Model("provider/proposer-b")])
        >> sf.Synthesize(synthesizer)
    )

    assert compiled.kind == "fusion"
    assert compiled.models == (
        "provider/proposer-a",
        "provider/proposer-b",
        "provider/editor-a",
        "provider/editor-b",
        "provider/final-editor",
    )
    assert [operation.depends_on for operation in compiled.operations] == [
        (),
        (),
        ("op_model_1", "op_model_2"),
        ("op_model_1", "op_model_2"),
        ("op_model_3", "op_model_4"),
    ]


def test_reusing_one_recipe_at_a_later_stage_creates_a_distinct_invocation() -> None:
    shared = sf.Model("provider/shared")

    compiled = compile_candidate(sf.Pipeline([shared, shared]))

    assert compiled.url4 is not None
    expression = build(compiled.url4)
    assert isinstance(expression, Expression)
    calls = [
        source.value
        for source in expression.sources
        if isinstance(source, Source) and isinstance(source.value, RelExpr)
    ]
    assert [(call.path, call.context) for call in calls] == [
        ("/provider/shared", "$input"),
        ("/provider/shared", "$model_1"),
    ]


def test_candidate_compilation_rejects_a_cycle_even_when_it_rebinds_input() -> None:
    pipeline = sf.Pipeline([sf.Model("provider/a"), sf.Model("provider/b")])
    object.__setattr__(pipeline, "stages", (sf.Model("provider/a"), pipeline))

    with pytest.raises(ValueError, match="cycle"):
        compile_candidate(pipeline)


def test_canonical_benchmark_plans_a_pipeline_as_one_complete_candidate() -> None:
    pipeline = sf.Pipeline(
        [
            sf.Model("provider/draft", params={"temperature": 0.4}),
            sf.Model("provider/review", params={"seed": 7}),
        ],
        name="review-chain",
    )

    evaluation = compile_evaluation((pipeline,), _whole_candidate_benchmark(), 1)
    candidate = evaluation.candidates.only

    assert candidate.name == "review-chain"
    assert candidate.kind == "pipeline"
    assert candidate.models == ("provider/draft", "provider/review")
    assert candidate.members == ()
    assert [operation.depends_on for operation in candidate.operations] == [
        (),
        ("op_model_1",),
    ]
    assert evaluation.required_models == candidate.models
    assert [(value.model, dict(value.params)) for value in candidate.parameter_assignments] == [
        ("provider/draft", {"temperature": 0.4}),
        ("provider/review", {"seed": 7}),
    ]


def test_structural_member_benchmark_rejects_a_pipeline_before_execution() -> None:
    structural = _decode_benchmark_resource(
        {
            "schema": "screamingface.benchmark.v1",
            "id": "fixture",
            "title": "Structural fixture",
            "description": "Requires direct Fusion members.",
            "revision": "fixture-revision",
            "case_count": 1,
            "url4": "(answer:0.0:/candidate?q=(question)!'$candidate_member_1')!'$answer'",
        },
        requested_id="fixture",
        requested_limit=1,
    )
    pipeline = sf.Pipeline([sf.Model("provider/a"), sf.Model("provider/b")])

    with pytest.raises(
        sf.PlanningError, match="unsupported structural Candidate bindings"
    ) as caught:
        compile_evaluation((pipeline,), structural, 1)

    assert caught.value.code == "candidate_shape_mismatch"
