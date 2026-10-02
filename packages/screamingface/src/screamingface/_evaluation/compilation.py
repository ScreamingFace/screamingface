"""Assemble a complete Evaluation from one Benchmark fetch and local Candidates."""

from __future__ import annotations

from collections.abc import Sequence

from screamingface._evaluation.answer_rule import _BenchmarkAnswerRule
from screamingface._evaluation.benchmark import _BenchmarkResource
from screamingface._evaluation.candidate import (
    _CompiledCandidate,
    compile_candidate,
)
from screamingface._evaluation.linking import _prepare_benchmark
from screamingface._evaluation.model import (
    _compiled_candidate,
    _compiled_evaluation,
    _Evaluation,
)
from screamingface._evaluation.operators import _OperatorCatalog
from screamingface.recipe import Recipe


def compile_evaluation(
    recipes: Sequence[Recipe],
    resource: _BenchmarkResource,
    limit: int | None,
    *,
    operators: _OperatorCatalog | None = None,
) -> _Evaluation:
    """Compile all Candidates locally against one selected Benchmark."""

    # FEATURE (GP-1): extract="benchmark" resolves here, at the plan seam, from the resource
    # already fetched; the compiled url4 then pins the rule's concrete operator ids.
    benchmark_rule = _BenchmarkAnswerRule(resource.info.id, resource.answer_rule)
    compiled = tuple(
        compile_candidate(
            recipe,
            check_surface=resource.check_surface,
            operators=operators,
            benchmark_rule=benchmark_rule,
        )
        for recipe in recipes
    )
    # WHY: the Benchmark is identical for every Candidate — parse it once and bind
    # each compiler-produced (already canonical) Candidate expression into it.
    prepared = _prepare_benchmark(resource.url4)
    linked = tuple(prepared.bind(value.url4) for value in compiled)
    candidates = []
    for recipe, value, result in zip(recipes, compiled, linked, strict=True):
        candidates.append(
            _compiled_candidate(
                name=recipe.name,
                kind=value.kind,
                models=value.models,
                url4=result.url4,
                operations=value.operations,
                members=value.members,
                parameter_assignments=value.parameter_assignments,
                known_operation_ids=_known_operation_ids(value),
            )
        )
    selected_candidates = tuple(candidates)

    return _compiled_evaluation(
        benchmark=resource.info,
        limit=limit,
        case_count=resource.case_count,
        candidates=selected_candidates,
        required_models=_ordered_unique(
            tuple(model for candidate in selected_candidates for model in candidate.models)
        ),
    )


def _known_operation_ids(candidate: _CompiledCandidate) -> tuple[str, ...]:
    values = tuple(operation.id for operation in candidate.operations) + tuple(
        member.operation_id for member in candidate.members
    )
    return tuple(dict.fromkeys(values))


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__: list[str] = []
